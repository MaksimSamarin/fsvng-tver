# -*- coding: utf-8 -*-
import io, os, re, html

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRCDIR = os.path.join(HERE, "исходники")
DIST = os.path.join(HERE, "dist")
SRC  = os.path.join(ROOT, "правовая", "источники")
TPL  = os.path.join(SRCDIR, "template.html")
OUT  = os.path.join(DIST, "памятка-курсанта.html")


def esc(s): return html.escape(s, quote=False)

def inline(s):
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    # внешние ссылки — кликабельные, внутренние (.md, пути базы) — только текст
    def link(m):
        t, u = m.group(1), m.group(2)
        if u.startswith("http"):
            return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (u, t)
        return t
    s = re.sub(r"\[([^\]]+)\]\(([^)]*)\)", link, s)
    # голые URL
    s = re.sub(r'(?<!["=>])(https?://[^\s<>"]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


SKIP_SECTION = re.compile(r"(примечан|расхожден|исходному тексту|открытые вопрос|что изменилось|заметк[аи] к|оговорк)", re.I)

META = re.compile(r"^\*{0,2}(Автор|Авторы|Источник|Схема постов|Действующая редакция|Актуальная редакция|Консолидированная редакция)\b", re.I)
def is_meta(line):
    """служебная шапка документа — авторство, даты, ссылка на оригинал"""
    return bool(META.match(line.strip()))

NAVHINT = re.compile(r"^(см\.|полн|подроб|готов|конспект|памятка для|условия и категории|источник:|📎)", re.I)
def is_nav(line):
    """строка-сноска на файл базы, которой у курсантов нет"""
    if ".md)" not in line and "](../" not in line and not re.search(r"\]\([^)]*\.md", line):
        return False
    bare = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line).strip(" ·—-")
    return bool(NAVHINT.match(bare)) or len(bare) < 46

# ---------- парсер устава ----------
def parse_charter(path, cls, skip_head=0):
    lines = [l.rstrip() for l in io.open(path, encoding="utf-8-sig").read().split("\n")]
    out, tocn = [], 0
    art = None
    def close():
        nonlocal art
        if art:
            body = "".join("<p>%s</p>" % inline(p) for p in art["body"] if p.strip())
            out.append(
                '<div class="art" id="%s" data-num="%s" data-title="%s">'
                '<p class="an"><i>%s</i><span>%s</span></p>%s</div>'
                % (art["id"], esc(art["num"]), esc(art["title"]), esc(art["num"]), esc(art["title"]), body))
            art = None
    for raw in lines[skip_head:]:
        l = raw.strip()
        if not l: continue
        if l.startswith("[") and l.endswith("]"): continue
        if l.startswith("---"): continue
        if re.match(r"^\*{0,2}(ГЛАВА|Глава)\b", l):
            close()
            t = re.sub(r"^\*+|\*+$", "", l)
            tocn += 1
            cid = "%s-ch%d" % (cls, tocn)
            short = re.sub(r"^(ГЛАВА|Глава)\s+[IVXL0-9]+\.?\s*", "", t)
            out.append('<h3 class="chapter" id="%s" data-short="%s">%s</h3>' % (cid, esc(short[:40] or t), esc(t)))
            continue
        m = re.match(r"^\*{0,2}Статья\s+([0-9]+(?:\.[0-9]+)*)\.?\s*(.*?)\*{0,2}$", l)
        if m:
            close()
            num, title = m.group(1), re.sub(r"^\*+|\*+$", "", m.group(2)).strip()
            art = {"num": num, "title": title or ("Статья " + num),
                   "id": "%s-a%s" % (cls, num.replace(".", "-")), "body": []}
            continue
        if l.upper().startswith("ПРЕАМБУЛА"):
            close()
            out.append('<h3 class="chapter" id="%s-pre" data-short="Преамбула">Преамбула</h3>' % cls)
            continue
        if art is not None:
            art["body"].append(l)
        else:
            out.append("<p>%s</p>" % inline(l))
    close()
    return "\n".join(out)


# ---------- кодексы РО (markdown с форума) ----------
# В УК состав и санкция в одном абзаце:   [Р/Ф] [***] Деяние, — наказывается штрафом ...
# В КоАП санкция вынесена в следующий:    1. [**] Деяние, -
#                                         влечет наложение административного штрафа ...
CODE_LINE = re.compile(r"^(\d+[.)]\s*)?((?:\[[^\]\n]{1,28}\]\s*)+)(.+)$")
PART_LINE = re.compile(r"^(\d+[.)])\s*(.+)$")
PEN_START = re.compile(r"^(наказывается|наказываются|влечёт|влечет|влекут)\b", re.I)
PEN_INLINE = re.compile(r"[,\s]*[\u2014\u2013-]\s*(наказывается|наказываются|влечёт|влечет|влекут)\s+", re.I)
CODE_SKIP = re.compile(r"^(Источник:|#|\*?[А-ЯЁ][^\n]*\u00b7\s*\d{4}-\d{2}-\d{2}\*?$)")
CODE_HEAD = re.compile(r"^(УГОЛОВНЫЙ КОДЕКС|КОДЕКС РО|ОБ АДМИНИСТРАТИВНЫХ)")
DASH_END = re.compile(r"[\u2014\u2013-]\s*$")


def code_body(paras):
    """Собирает тело статьи: карточка «состав → наказание» с метками приоритета розыска."""
    # санкция, вынесенная в отдельный абзац, приклеивается к своему составу
    merged = []
    for t in paras:
        if merged and PEN_START.match(t) and not merged[-1].startswith("Примечание"):
            merged[-1] = DASH_END.sub("", merged[-1]).rstrip(" ,") + " \u2014 " + t
        else:
            merged.append(t)

    html_out = []
    for l in merged:
        if l.startswith("Примечание"):
            html_out.append('<p class="prim">%s</p>' % inline(l))
            continue

        part, tags, body = "", [], l
        m = CODE_LINE.match(l)
        if m:
            part = (m.group(1) or "").strip()
            tags = re.findall(r"\[([^\]]+)\]", m.group(2))
            body = m.group(3)
        else:
            mp = PART_LINE.match(l)
            if mp:
                part, body = mp.group(1), mp.group(2)

        sp = PEN_INLINE.split(body, 1)
        if len(sp) != 3:
            # обычный абзац статьи — без состава и санкции
            txt = ("<b>%s</b> " % esc(part) if part else "") + inline(body)
            html_out.append("<p>%s</p>" % txt)
            continue

        deed, verb, pen = sp[0].rstrip(" ,"), sp[1].lower(), sp[2]
        chips = ""
        if part:
            chips += '<b class="pnum">%s</b>' % esc(part.rstrip(".)"))
        for t in tags:
            t = t.strip()
            cl = "st" if ("\u2605" in t or t.lower().startswith("от ")) else "rf"
            chips += '<b class="%s">%s</b>' % (cl, esc(t))
        head = '<p class="ptags">%s</p>' % chips if chips else ""
        html_out.append('<div class="pun">%s<p class="deed">%s</p>'
                        '<p class="pen"><i>%s</i>%s</p></div>'
                        % (head, inline(deed), esc(verb), inline(pen)))
    return "".join(html_out)


def parse_code(path, cls):
    """Разбирает кодекс: разделы, главы, статьи, составы с приоритетом розыска."""
    raw = io.open(path, encoding="utf-8-sig").read().replace("**", "")
    out, nch = [], 0
    art = None

    def close():
        nonlocal art
        if art:
            out.append(
                '<div class="art" id="%s" data-num="%s" data-title="%s">'
                '<p class="an"><i>%s</i><span>%s</span></p>%s</div>'
                % (art["id"], esc(art["num"]), esc(art["title"]),
                   esc(art["num"]), esc(art["title"]), code_body(art["raw"])))
            art = None

    def chapter(text, short, extra=""):
        nonlocal nch
        nch += 1
        out.append('<h3 class="chapter%s" id="%s-ch%d" data-short="%s">%s</h3>'
                   % (extra, cls, nch, esc(short[:42]), esc(text)))

    for raw_line in raw.split("\n"):
        l = raw_line.strip()
        if not l or l.startswith("---") or CODE_SKIP.match(l) or CODE_HEAD.match(l):
            continue

        if re.match(r"^РАЗДЕЛ\s+[IVXL]+", l):
            close()
            chapter(l, re.sub(r"^РАЗДЕЛ\s+[IVXL]+\.?\s*", "", l) or l)
            continue

        if re.match(r"^Глава\s+[0-9]+", l):
            close()
            chapter(l, re.sub(r"^Глава\s+[0-9]+\.?\s*", "", l) or l, " ch2")
            continue

        m = re.match(r"^Статья\s+([0-9]+(?:\.[0-9]+)*)\.?\s*(.*)$", l)
        if m:
            close()
            num, title = m.group(1), m.group(2).strip()
            art = {"num": num, "title": title or ("Статья " + num),
                   "id": "%s-a%s" % (cls, num.replace(".", "-")), "raw": []}
            continue

        if art is not None:
            art["raw"].append(l)

    close()
    return "\n".join(out)

# ---------- markdown → html ----------
def md2html(path, idp):
    txt = io.open(path, encoding="utf-8").read()
    lines = txt.split("\n")
    out, i, n = [], 0, 0
    intbl = False
    while i < len(lines):
        l = lines[i].rstrip()
        s = l.strip()
        if s.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            n += 1
            cid = "%s-c%d" % (idp, n)
            body = "\n".join(buf)
            short_say = len(buf) == 1 and len(body) < 90 and not body.lstrip().startswith("/")
            if short_say:
                out.append('<p class="say">%s</p>' % esc(body))
            else:
                out.append('<div class="cmd"><pre id="%s">%s</pre><button class="cp" data-c="%s">Копировать</button></div>'
                           % (cid, esc(body), cid))
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip()); i += 1
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            if len(cells) >= 2 and set("".join(cells[1]).replace(" ", "")) <= set("-:"):
                head, body = cells[0], cells[2:]
            else:
                head, body = None, cells
            t = ['<div class="tw"><table>']
            if head: t.append("<thead><tr>" + "".join("<th>%s</th>" % inline(c) for c in head) + "</tr></thead>")
            t.append("<tbody>")
            for r in body:
                t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue
        if s.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            out.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(buf)))
            continue
        if re.match(r"^[-*] ", s):
            buf = []
            while i < len(lines) and re.match(r"^[-*] ", lines[i].strip()):
                buf.append(lines[i].strip()[2:]); i += 1
            buf = [x for x in buf if not is_nav(x)]
            if buf:
                out.append('<ul class="md">' + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ul>")
            continue
        if re.match(r"^\d+\. ", s):
            buf = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i].strip()):
                buf.append(re.sub(r"^\d+\.\s*", "", lines[i].strip())); i += 1
            out.append('<ol class="md">' + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ol>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl, t = len(m.group(1)), m.group(2)
            i += 1
            if SKIP_SECTION.search(t):          # редакторский блок — пропускаем целиком
                while i < len(lines):
                    m2 = re.match(r"^(#{1,4})\s+", lines[i].strip())
                    if m2 and len(m2.group(1)) <= lvl: break
                    i += 1
                continue
            if lvl == 1: continue
            if lvl == 2:
                n += 1
                out.append('<h3 class="chapter" id="%s-h%d" data-short="%s">%s</h3>' % (idp, n, esc(t[:38]), inline(t)))
            else:
                out.append("<h4>%s</h4>" % inline(t))
            continue
        if s.startswith("---"):
            i += 1; continue
        if s and not is_nav(s) and not is_meta(s):
            out.append("<p>%s</p>" % inline(s))
        i += 1
    return "\n".join(out)

CH_REPORT = "https://discord.com/channels/1538938584441163776/1542813994312798269"
CH_REQUEST = "https://discord.com/channels/1538938584441163776/1541938339240869958"
CH_TICKET = "https://discord.com/channels/1538938584441163776/1538938589105225761"

CHAN_RULES = [
    (re.compile(r"(?:#\s*)?(?:🛡️\s*)?отч[её]т-на-повышение-курсанты"), CH_REPORT, "отчет-на-повышение-курсанты"),
    (re.compile(r"(?:#\s*)?(?:╏\s*)?(?:📘\s*)?(?:・\s*)?запрос-на-повышения"), CH_REQUEST, "запрос-на-повышения"),
    (re.compile(r"(?:#\s*)?(?:╏\s*)?(?:📘\s*)?(?:・\s*)?запрос-военных-билетов"), CH_TICKET, "запрос-военных-билетов"),
]

def chanlinks(h):
    """упоминания каналов в тексте → кликабельные ссылки (кроме уже готовых <a>)"""
    parts = re.split(r"(<a\b[^>]*>.*?</a>)", h, flags=re.S)
    for i in range(0, len(parts), 2):
        for rx, url, label in CHAN_RULES:
            parts[i] = rx.sub('<a class="chl" href="%s" title="Откроется в приложении Discord">#%s</a>' % (app_link(url), label), parts[i])
    return "".join(parts)

CHANS_CARDS = '''<div class="chans">
  <a class="chan ch1" href="discord://-/channels/1538938584441163776/1542813994312798269">
    <span class="cn">Шаг 1</span><span class="ct">Отчёт на повышение</span>
    <span class="cd">Курсанты подают сюда отчёт с доказательствами. Ждём проверки и отметки ✅</span>
    <span class="cl">отчет-на-повышение-курсанты</span></a>
  <a class="chan ch2" href="discord://-/channels/1538938584441163776/1541938339240869958">
    <span class="cn">Шаг 2</span><span class="ct">Запрос на повышение</span>
    <span class="cd">Отписываем <strong>после одобрения отчёта</strong>, приложив ссылку на одобренное сообщение</span>
    <span class="cl">запрос-на-повышения</span></a>
  <a class="chan ch3" href="discord://-/channels/1538938584441163776/1538938589105225761">
    <span class="cn">С 6 ранга</span><span class="ct">Запрос военного билета</span>
    <span class="cd">Подаём по достижении 6 ранга, затем находим старший состав ФСВНГ для выдачи</span>
    <span class="cl">запрос-военных-билетов</span></a>
</div>'''

CHANS = '''<h3 class="chapter" id="chans" data-short="Каналы Discord">Каналы Discord</h3>
<p>Три канала, через которые проходит весь путь повышения. Порядок строгий: сначала отчёт, после одобрения — запрос.</p>
<div class="chans">
  <a class="chan ch1" href="discord://-/channels/1538938584441163776/1542813994312798269">
    <span class="cn">Шаг 1</span><span class="ct">Отчёт на повышение</span>
    <span class="cd">Курсанты подают сюда отчёт с доказательствами. Ждём проверки и отметки ✅</span>
    <span class="cl">отчет-на-повышение-курсанты</span></a>
  <a class="chan ch2" href="discord://-/channels/1538938584441163776/1541938339240869958">
    <span class="cn">Шаг 2</span><span class="ct">Запрос на повышение</span>
    <span class="cd">Отписываем <strong>после одобрения отчёта</strong>, приложив ссылку на одобренное сообщение</span>
    <span class="cl">запрос-на-повышения</span></a>
  <a class="chan ch3" href="discord://-/channels/1538938584441163776/1538938589105225761">
    <span class="cn">С 6 ранга</span><span class="ct">Запрос военного билета</span>
    <span class="cd">Подаём по достижении 6 ранга, затем находим старший состав ФСВНГ для выдачи</span>
    <span class="cl">запрос-военных-билетов</span></a>
</div>'''

PH = {}
try:
    import json
    PH = json.loads(io.open(os.path.join(SRCDIR, "photos.json"), encoding="utf-8").read())
except Exception as e:
    print("фото не подключены:", e)

def img(key, alt, cap=None):
    src = PH.get(key)
    if not src:
        return ""
    c = '<figcaption>%s</figcaption>' % esc(cap) if cap else ""
    return '<figure class="ph"><img src="%s" alt="%s" loading="lazy">%s</figure>' % (src, esc(alt), c)

def post_card(key, name, meta, desc, mine=True):
    return ('<div class="post %s"><div class="pm">%s</div><div class="pn">%s</div><div class="pd">%s</div>'
            '%s%s</div>' % ("mine" if mine else "", meta, name, desc,
                            img("post-%s-photo" % key, "Пост %s" % name),
                            img("post-%s-map" % key, "Метка на карте: %s" % name, "Метка на карте")))

POSTS_GRID = ('<div class="posts wide">'
    + post_card("kpp1", "КПП №1 Алабино", "Пост Росгвардии",
                "Двое военнослужащих слева и справа от ворот, один за воротами. Основной пункт прохода, въезда и выезда")
    + post_card("kpp2", "КПП №2 Алабино", "Пост Росгвардии",
                "Двое слева и справа от шлагбаума, один за шлагбаумом. На полигоне оба КПП равнозначны")
    + post_card("tower", "Наблюдательная вышка", "Наблюдение",
                "Двое военнослужащих. Визуальный контроль территории, выявление проникновения, доклад по связи", False)
    + '</div>'
    + '<h4>Вышки по распоряжению командования</h4>'
    + '<div class="posts wide">'
    + post_card("oruj", "Вышка «Оружейки»", "Один военнослужащий", "Наблюдение за складской зоной", False)
    + post_card("ogn", "Вышка «Огневой рубеж»", "Один военнослужащий", "Наблюдение за стрельбищем", False)
    + post_card("lager", "Вышка «Лагерь»", "Один военнослужащий", "Наблюдение за лагерной зоной", False)
    + '</div>')

DRESS = ('<h3 class="chapter" id="dress" data-short="Дресс-код ФСВНГ">Дресс-код ФСВНГ</h3>'
    '<p>Шестой документ лекции по внутренним НПА. По <strong>ст. 3.1 Устава ВС</strong> форма обязана соответствовать '
    'подразделению и воинскому званию, по <strong>ст. 3.2</strong> запрещены неустановленные знаки различия. '
    'Нарушение правил ношения формы — <strong>ст. 17 ДУ</strong>.</p>'
    '<div class="gal">'
    + '<div class="gc"><div class="gt">Академия ФСВНГ</div><div class="gs">Мужская</div>' + img("dress-akad-m", "Форма Академии ФСВНГ, мужская") + '</div>'
    + '<div class="gc"><div class="gt">Академия ФСВНГ</div><div class="gs">Женская</div>' + img("dress-akad-w", "Форма Академии ФСВНГ, женская") + '</div>'
    + '<div class="gc"><div class="gt">ОМОН ФСВНГ</div><div class="gs">Подразделение</div>' + img("dress-omon", "Форма ОМОН ФСВНГ") + '</div>'
    + '<div class="gc"><div class="gt">ОСБ ФСВНГ</div><div class="gs">Подразделение</div>' + img("dress-osb", "Форма ОСБ ФСВНГ") + '</div>'
    + '<div class="gc"><div class="gt">РВО ФСВНГ</div><div class="gs">Подразделение</div>' + img("dress-rvo", "Форма РВО ФСВНГ") + '</div>'
    + '<div class="gc"><div class="gt">Парадная форма</div><div class="gs">Мужская · начальство, Кадровая служба</div>' + img("dress-parad-m", "Парадная форма ФСВНГ, мужская") + '</div>'
    + '<div class="gc"><div class="gt">Парадная форма</div><div class="gs">Женская · начальство, Кадровая служба</div>' + img("dress-parad-w", "Парадная форма ФСВНГ, женская") + '</div>'
    + '</div>'
    '<h4 id="oath-uniform">Форма на присягу</h4>'
    '<div class="gal">'
    + '<div class="gc"><div class="gt">Старший офицер</div><div class="gs">Парадный китель с брюками</div>' + img("dress-oath-off", "Форма старшего офицера на присяге") + '</div>'
    + '<div class="gc"><div class="gt">Дающий присягу</div><div class="gs">Парадный мундир с брюками</div>' + img("dress-oath-cadet", "Форма дающего присягу") + '</div>'
    + '</div>')

def unit(x, y, label, kind="u", r=17):
    return ('<circle class="u %s" cx="%d" cy="%d" r="%d"/><text class="ul %s" x="%d" y="%d">%s</text>'
            % (kind, x, y, r, kind, x, y, label))

def _row(xs, y, labels, kinds=None):
    kinds = kinds or ["u"] * len(labels)
    return "".join(unit(x, y, l, k) for x, l, k in zip(xs, labels, kinds))

# ——— схема 1: шеренга и колонна ———
_sh = [70, 130, 190, 250, 310]
SCH1 = ('<figure class="ph sch-wrap"><svg class="sch" viewBox="0 0 700 190" role="img" '
    'aria-label="Шеренга — военнослужащие в одну линию на интервалах. Колонна — друг за другом в затылок">'
    '<text class="cap" x="12" y="20">Шеренга</text>'
    '<text class="cap" x="430" y="20">Колонна</text>'
    + _row(_sh, 70, ["", "", "", "", ""])
    + '<line class="ln dim" x1="70" y1="104" x2="310" y2="104"/>'
      '<text class="sub" x="190" y="124">в одну линию на равных интервалах</text>'
      '<path class="ar" d="M86 70 l12 -7 v14 z"/><text class="sub" x="150" y="152">фронт →</text>'
    + "".join(unit(520, y, "") for y in (52, 92, 132))
    + '<line class="ln dim" x1="547" y1="52" x2="547" y2="132"/>'
      '<text class="sub" x="576" y="96">друг за другом</text>'
      '<text class="sub" x="576" y="114">в затылок</text>'
    '</svg><figcaption>Шеренга и колонна — базовые построения</figcaption></figure>')

# ——— схема 2: построение роты ———
_front = [70, 130, 190, 250, 310]
SCH2 = ('<figure class="ph sch-wrap"><svg class="sch" viewBox="0 0 700 250" role="img" '
    'aria-label="Построение роты: в первой шеренге старшие по званию, заместитель командира и командир; '
    'за ними в затылок младшие по званию">'
    '<text class="cap" x="12" y="20">Построение роты</text>'
    + '<line class="ln" x1="70" y1="78" x2="70" y2="176"/>'
      '<line class="ln" x1="130" y1="78" x2="130" y2="176"/>'
      '<line class="ln" x1="190" y1="78" x2="190" y2="176"/>'
    + _row(_front, 60, ["С", "С", "С", "ЗК", "К"], ["u", "u", "u", "zk", "k"])
    + _row([70, 130, 190], 194, ["М", "М", "М"])
    + '<path class="ar" d="M370 60 l14 -8 v16 z"/><text class="sub" x="392" y="65">фронт</text>'
      '<text class="sub" x="392" y="196">тыл</text>'
      '<text class="sub" x="392" y="128">дистанция между шеренгами</text>'
    '</svg><figcaption>Рота: старшие по званию впереди, младшие — за ними в затылок</figcaption></figure>')

# ——— схема 3: несколько рот ———
def _company(x0, n):
    xs = [x0, x0 + 44, x0 + 88, x0 + 132, x0 + 176]
    return ('<text class="cap sm" x="%d" y="34">Рота %d</text>' % (x0 + 60, n)
            + _row(xs, 66, ["С", "С", "С", "ЗК", "К"], ["u", "u", "u", "zk", "k"])
            + _row([x0, x0 + 44, x0 + 88], 170, ["М", "М", "М"])
            + '<line class="ln" x1="%d" y1="80" x2="%d" y2="156"/>' % (x0, x0)
            + '<line class="ln" x1="%d" y1="80" x2="%d" y2="156"/>' % (x0 + 44, x0 + 44)
            + '<line class="ln" x1="%d" y1="80" x2="%d" y2="156"/>' % (x0 + 88, x0 + 88))

SCH3 = ('<figure class="ph sch-wrap wide"><svg class="sch" viewBox="0 0 760 210" role="img" '
    'aria-label="Построение нескольких рот с интервалом в одного военнослужащего между ними">'
    + _company(40, 1) + _company(280, 2) + _company(520, 3)
    + '<text class="int" x="248" y="72">1</text><text class="int" x="488" y="72">1</text>'
      '<text class="sub" x="248" y="98" text-anchor="middle">интервал</text>'
      '<text class="sub" x="488" y="98" text-anchor="middle">интервал</text>'
    '</svg><figcaption>Несколько рот: между ротами интервал, равный одному военнослужащему</figcaption></figure>')

LEGEND = ('<div class="leg">'
    '<div class="li"><span class="lu k">К</span><span>Командир</span></div>'
    '<div class="li"><span class="lu zk">ЗК</span><span>Заместитель командира</span></div>'
    '<div class="li"><span class="lu">С</span><span>Старший по званию</span></div>'
    '<div class="li"><span class="lu">М</span><span>Младший по званию</span></div>'
    '<div class="li"><span class="lu int">1</span><span>Интервал, равный одному военнослужащему</span></div>'
    '</div>')

STROY_FIGS = ('<h4>Схемы строёв</h4>' + LEGEND + SCH1 + SCH2 + SCH3)

def vch_card(key, name, meta, desc, mine=False):
    return ('<div class="post %s"><div class="pm">%s</div><div class="pn">%s</div><div class="pd">%s</div>%s</div>'
            % ("mine" if mine else "", meta, name, desc, img("%s" % key, "Пост %s" % name)))

POSTS_VCH = ('<h3 class="chapter" id="posts-vch" data-short="Посты воинской части">Посты и дежурства воинской части</h3>'
    '<p>Восемь постов на территории самой воинской части — отдельно от полигона «Алабино». '
    'По <strong>ст. 22 УКПС</strong> перечень постов части: КПП №1 (главный), КПП №2 (запасной), вышки по периметру, '
    'главный склад и военный полигон. Расстановка ниже — по схеме дежурств.</p>'
    '<h4>Контрольно-пропускные пункты</h4>'
    '<div class="posts wide">'
    + vch_card("vch-kpp1", "КПП №1", "Главный КПП", "Двое военнослужащих слева и справа от ворот, один за воротами", True)
    + vch_card("vch-kpp2", "КПП №2", "Запасной КПП", "Двое военнослужащих слева и справа от ворот, один за воротами", True)
    + '</div>'
    '<h4>Вышки по периметру</h4>'
    '<div class="posts wide">'
    + vch_card("vch-vkpp1", "Вышка «КПП №1»", "Один военнослужащий", "Наблюдение над главным КПП")
    + vch_card("vch-avto", "Вышка «Автопарк»", "Один военнослужащий", "Наблюдение за автопарком")
    + vch_card("vch-bober", "Вышка «Бобёр»", "Один военнослужащий", "Тыловая сторона КПП №1")
    + vch_card("vch-tyl", "Вышки «Тыл»", "Два военнослужащих", "За авиационной полосой")
    + '</div>'
    '<h4>Автопарк</h4>'
    '<div class="posts wide">'
    + vch_card("vch-ap1", "КПП «Автопарк №1»", "Два военнослужащих", "Один в КПП, другой слева от него")
    + vch_card("vch-ap2", "КПП «Автопарк №2»", "Два военнослужащих", "Один в КПП, другой слева от него")
    + '</div>'
    '<div class="note"><div class="h">Не путать с полигоном</div>Посты воинской части и посты полигона «Алабино» — '
    'разные объекты. Караул курсанта на повышение 2 → 3 несётся на <strong>КПП №1 или КПП №2 полигона Алабино</strong>.</div>')

POSTS = '''<h3 class="chapter" id="posts" data-short="Посты на Алабино">Посты на полигоне «Алабино»</h3>
<p>По <strong>ст. 22.1 УКПС</strong> на полигоне три постоянных поста. Дежурство несут военнослужащие мотострелкового корпуса и роты вневедомственной охраны. <strong>Курсанты и сотрудники Росгвардии заступают на КПП №1 и КПП №2</strong> — именно они указываются в докладе и в отчёте на повышение.</p>
''' + POSTS_GRID + '''
<p>Дополнительно лекция по постовой службе называет вышки «Оружейки», «Огневой рубеж» и «Лагерь» — по одному военнослужащему. Уставом как постоянные посты они не закреплены и выставляются по распоряжению командования.</p>'''

OATH_GAL = ('<a class="xl" href="#oath-uniform" data-pane="p-le" data-anchor="oath-uniform">посмотреть обе формы на фото →</a>')

def dochead(cls, abbr, title, sub, facts):
    f = "".join("<span>%s</span>" % x for x in facts)
    return ('<div class="dochead %s"><div class="abbr">%s</div><h2>%s</h2>'
            '<p class="sub">%s</p><div class="facts">%s</div></div>' % (cls, abbr, title, sub, f))

# ---------- панели уставов ----------
vu = dochead("dv", "Основной документ", "Устав ВС РФ и ФСВНГ",
             "Общий порядок службы: распорядок дня, форма одежды, структура, служебная связь, регламент действий и кадровая отчётность.",
             ["Консолидированная редакция", "8 глав", "Действует для <b>ВС и ФСВНГ</b>"]) + \
     parse_charter(os.path.join(SRC, "устав-вс-и-фсвнг_оригинал.txt"), "vu", 2)

du = dochead("dd", "Дисциплина", "Дисциплинарный устав",
             "Виды дисциплинарных проступков, меры взыскания, порядок их применения и поощрения военнослужащих.",
             ["Редакция <b>10.09.2026</b>", "35 статей", "ФСВНГ ведёт <b>ОСБ</b>"]) + \
     parse_charter(os.path.join(SRC, "дисциплинарный-устав_оригинал.txt"), "du", 4)

uk = dochead("du_", "Служба на посту", "Устав караульно-постовой службы",
             "Главный документ на посту: перечень постов, заступление и сдача, пропускной режим, досмотр и запреты на КПП.",
             ["Консолидированная редакция", "44 статьи", "Посты на <b>Алабино</b>"]) + \
     parse_charter(os.path.join(SRC, "устав-караульно-постовой-службы_оригинал.txt"), "uk", 2)

D = os.path.join(ROOT, "docs")
le = dochead("dl", "Внутренние материалы", "Лекции ФСВНГ",
             "Лекция проводится инструктором <strong>разово и сразу по всем документам</strong> — постовая служба, "
             "субординация, строевая подготовка, дресс-код, Дисциплинарный устав и Устав ВС. "
             "Экзамен тоже <strong>один, по всему материалу целиком</strong>, а не по каждому блоку отдельно.",
             ["Одна лекция — <b>6 документов</b>", "Присяга и посты", "Экзамен на ранге <b>2 → 3</b>"]) + \
     md2html(os.path.join(D, "лекция-постовая-служба.md"), "le1") + POSTS + POSTS_VCH + \
     md2html(os.path.join(D, "лекция-субординация.md"), "le2") + \
     md2html(os.path.join(D, "лекция-строевая-подготовка.md"), "le3") + STROY_FIGS + \
     md2html(os.path.join(D, "присяга.md"), "le4").replace("OATH-UNIFORM-GALLERY", OATH_GAL) + DRESS



def web_of(app):
    """discord://-/... → обычная https-ссылка"""
    if app.startswith("discord://-/channels/"):
        return "https://discord.com/channels/" + app.split("/channels/")[1]
    if app.startswith("discord://-/invite/"):
        return "https://discord.gg/" + app.split("/invite/")[1]
    return app

def app_link(url):
    """https-ссылка Discord → протокол приложения discord://"""
    m = re.match(r"https://discord\.com/channels/([\d@mel]+)/(\d+)(?:/(\d+))?", url)
    if m:
        tail = "/".join(x for x in m.groups() if x)
        return "discord://-/channels/" + tail
    m = re.match(r"https://discord\.gg/(\w+)", url)
    if m:
        return "discord://-/invite/" + m.group(1)
    return url

def chan_pair(url, label, cls=""):
    """кнопка в приложение + мелкая ссылка в браузер"""
    return ('<a class="%s" href="%s">%s</a>'
            '<a class="webalt" href="%s" target="_blank" rel="noopener" title="Открыть в браузере">в браузере</a>'
            % (cls, app_link(url), label, url))

def xl(text, pane, anchor):
    return '<a class="xl" href="#%s" data-pane="%s" data-anchor="%s">%s</a>' % (anchor, pane, anchor, text)

def links(*items):
    return '<div class="xlinks"><span class="xh">Материалы</span>' + "".join(items) + '</div>'

def task(n, title, body, proof=None, proof_ok=False):
    pr = ('<span class="proof %s">%s</span>' % ("ok" if proof_ok else "", proof)) if proof else ""
    return '<div class="task"><span class="tn">%d</span><div class="tt">%s</div><div class="td">%s%s</div></div>' % (n, title, body, pr)

ROUTE = ('<div class="route">'
 '<div class="rstep now"><span class="rr">Ранг 1</span><span class="rt">Кадет</span><span class="rd">Стартовый ранг. Выезд из части — только с Кадровой службой</span></div>'
 '<div class="rstep"><span class="rr">Ранг 2</span><span class="rt">Ефрейтор</span><span class="rd">После лекции, экскурсии, спец. связи и физподготовки</span></div>'
 '<div class="rstep"><span class="rr">Ранг 3</span><span class="rt">Мл. сержант</span><span class="rd">После присяги, стрельбища, полосы, караула и экзамена</span></div>'
 '<div class="rstep"><span class="rr">После 3</span><span class="rt">Подразделение</span><span class="rd">ОМОН · РВО · ОСБ · Кадровая служба — выбираешь сам</span></div>'
 '<div class="rstep fin"><span class="rr">Ранг 6</span><span class="rt">Военный билет</span><span class="rd">Старшина, 6+ дней во фракции</span></div>'
 '</div>')

STAGE12 = ('<div class="stage"><div class="stage-h"><h3 class="chapter sg" id="ru-st12" data-short="Ранг 1 → 2">Ранг 1 → 2</h3>'
 '<span class="cnt">5 задач</span><span class="note-inline">Выезд за территорию ВЧ — только с Кадровой службой</span></div>'
 '<div class="tasks">'
 + task(1, "Получить удостоверение",
        "<p>Оформляется в здании правительства. Выезд туда — в сопровождении сотрудника Кадровой службы ФСВНГ, самостоятельно ехать нельзя.</p>")
 + task(2, "Прослушать лекцию по внутренним НПА",
        "<p>Инструктор проводит её <strong>разово и сразу по всем шести документам:</strong></p>"
        "<ol><li>Лекция «Постовая служба»</li><li>Лекция по субординации</li><li>Лекция «Строевая подготовка»</li>"
        "<li>Дресс-код ФСВНГ</li><li>Дисциплинарный устав</li><li>Устав ВС РФ и ФСВНГ</li></ol>"
        "<p>Экзамен здесь не сдаётся — он будет на этапе 2 → 3.</p>"
        + links(xl("Постовая служба", "p-le", "le1-h7"), xl("Субординация", "p-le", "le2-h3"),
                xl("Строевая подготовка", "p-le", "le3-h1"), xl("Дресс-код", "p-le", "dress"),
                xl("Дисциплинарный устав", "p-du", "du-a6"), xl("Устав ВС", "p-vu", "vu-a1-1")))
 + task(3, "Прослушать лекцию-экскурсию по ВЧ",
        "<p>Проводит инструктор на территории части. Заранее посмотри, где какие посты — на экскурсии спросят.</p>"
        + links(xl("Посты воинской части", "p-le", "posts-vch"), xl("Посты на Алабино", "p-le", "posts")))
 + task(4, "Подключиться к государственной спец. связи",
        '<ol><li>Вступить в спец. связь «Государственные фракции РО»: '
        '<a href="discord://-/invite/5kTutqS8K">discord.gg/5kTutqS8K</a>'
        '<a class="webalt" href="https://discord.gg/5kTutqS8K" target="_blank" rel="noopener">в браузере</a></li>'
        '<li>Нажать <strong>«Получить роль»</strong>. Роль гос. служащего пока недоступна — берёте <strong>только Тверской</strong>: '
        '<a href="discord://-/channels/1538879177917210668/1538884293592354900/1543186737965309994">сообщение с кнопкой</a>'
        '<a class="webalt" href="https://discord.com/channels/1538879177917210668/1538884293592354900/1543186737965309994" target="_blank" rel="noopener">в браузере</a></li>'
        '<li>Появится подтверждение о выдаче роли</li>'
        '<li>Изменить ник по форме <code>Армия | Имя Фамилия | Статик</code></li></ol>'
        + links(xl("Требования к скриншотам", "p-memo", "s12")),
        "Скриншот профиля: роль Тверской + ник по форме")
 + task(5, "Пройти занятие по физподготовке",
        "<p>Проводит инструктор.</p>"
        + links(xl("Требования к скриншотам", "p-memo", "s12")), "2 скриншота: начало и конец")
 + '</div></div>')

STAGE23 = ('<div class="stage"><div class="stage-h"><h3 class="chapter sg" id="ru-st23" data-short="Ранг 2 → 3">Ранг 2 → 3</h3>'
 '<span class="cnt">5 задач</span><span class="note-inline">После 3 ранга выбираешь подразделение</span></div>'
 '<div class="tasks">'
 + task(1, "Принять присягу",
        "<p>Ежедневно в <strong>12:00 и 20:00 на плацу</strong>, либо в другое время по договорённости. ""Отыгрывается строго по процедуре: <a class=\"xl\" href=\"#le4-h1\" data-pane=\"p-le\" data-anchor=\"le4-h1\">открыть порядок проведения с репликами →</a>. "
        "Перед строем снять бронежилет и убрать оружие из-за спины.</p>"
        + links(xl("Как проходит присяга", "p-le", "le4-h1"), xl("Требования к скриншотам", "p-memo", "s12")),
        "1 скриншот принятия присяги")
 + task(2, "Отстрелять на стрельбище",
        "<p>Практическое занятие с инструктором.</p>"
        + links(xl("Требования к скриншотам", "p-memo", "s12")), "2 скриншота: начало и завершение")
 + task(3, "Пройти тренировочную площадку",
        "<p>Полоса препятствий.</p>"
        + links(xl("Требования к скриншотам", "p-memo", "s12")), "2 скриншота: начало и конец")
 + task(4, "Отстоять караул 1 час",
        "<p>Пост — <strong>КПП №1 или КПП №2 полигона «Алабино»</strong>. Доклад в <code>/f</code> каждые 15 минут. "
        "Заступил в 16:00 → доклады и скриншоты в 16:00, 16:15, 16:30, 16:45, 17:00.</p>"
        "<p>Экипировка полная: бронежилет, оружие, патроны, сухпайки. Бодикамера включена.</p>"
        + links(xl("Шаблоны докладов", "p-le", "le1-h1"), xl("Где стоять на посту", "p-le", "posts"),
                xl("Что запрещено на КПП", "p-uk", "uk-a36"), xl("Задачи караульного", "p-le", "le1-h7"),
                xl("При проникновении", "p-le", "le1-h8"), xl("Требования к скриншотам", "p-memo", "s12")),
        "5 скриншотов с докладами")
 + task(5, "Сдать экзамен по внутренним НПА",
        "<p><strong>Один экзамен сразу по всем шести документам</strong>, а не по каждому блоку отдельно.</p>"
        + links(xl("Памятка — что учить", "p-memo", "s1"), xl("20 вопросов к экзамену", "p-ex", "p-ex")),
        "1 скриншот результата")
 + '</div></div>')

FORM_REQUEST = """@Ваш тэг
1. Имя Фамилия Статик
2. Текущий ранг - ранг на который повышаетесь
3. Ссылка на одобренный отчет на повышение
@[👮] Инструктор КС ФСВНГ"""

FORM_EXAMPLE = """@!Комиссар | В. Гуров | 13053
1. Владислав Гуров 13053
2. 2-3 ранг
3. [ссылка на одобренный отчёт]
@[👮] Инструктор КС ФСВНГ"""

GFORM = "https://docs.google.com/forms/d/e/1FAIpQLSfbwGdN5GDH8ZOyQWyjBuToUWGr-g03veAsFkhylA7lY7-Dsw/viewform"

SUBMIT = ('<h3 class="chapter" id="ru-submit" data-short="Подача отчёта">Как подать отчёт и запрос</h3>'
 '<p>Два шага, порядок строгий: сначала отчёт через Google-форму, дождаться одобрения — и только потом запрос на повышение в Discord.</p>'
 '<div class="steps2">'
 '<div class="st2"><span class="s2n">Шаг 1</span><div class="s2t">Отчёт на повышение</div>'
 '<div class="s2d">Подаётся через Google-форму. Прикладываются доказательства по всем задачам этапа.</div>'
 '<a class="s2b" href="' + GFORM + '" target="_blank" rel="noopener">Открыть форму отчёта →</a></div>'
 '<div class="st2"><span class="s2n">Шаг 2</span><div class="s2t">Запрос на повышение</div>'
 '<div class="s2d">Только после одобрения отчёта. В запрос вкладывается ссылка на одобренный отчёт.</div>'
 '<a class="s2b" href="' + app_link(CH_REQUEST) + '">Открыть канал запроса →</a>'
 '<a class="webalt" href="' + CH_REQUEST + '" target="_blank" rel="noopener">в браузере</a></div>'
 '</div>'
 '<h4>Форма запроса на повышение</h4>'
 '<div class="cmd"><pre id="ru-form">' + esc(FORM_REQUEST) + '</pre>'
 '<button class="cp" data-c="ru-form">Копировать</button></div>'
 '<h4>Пример</h4>'
 '<div class="cmd"><pre id="ru-ex">' + esc(FORM_EXAMPLE) + '</pre>'
 '<button class="cp" data-c="ru-ex">Копировать</button></div>'
 '<div class="note bad"><div class="h">Строго заполнять по форме</div>'
 '<p style="margin:0">Последней строкой у нас всегда <code>@[👮] Инструктор КС ФСВНГ</code>. Заявка не по форме не рассматривается.</p></div>')

AFTER = ('<h3 class="chapter" id="ru-after" data-short="Что дальше">Что дальше</h3>'
 '<p><strong>После 3 ранга</strong> выбираешь подразделение: ОМОН, РВО, ОСБ или Кадровая служба ФСВНГ.</p>'
 '<p><strong>С 6 ранга</strong> (звание «Старшина») можно подать на военный билет — условия: не менее 6 дней во фракции '
 'с момента призыва и служба в учебном корпусе с 1 по 3 ранг. Заявка подаётся в канал #запрос-военных-билетов, '
 'после чего нужно найти старший состав ФСВНГ для выдачи.</p>')

PROOFS = ('<h3 class="chapter" id="ru-proofs" data-short="Доказательства">Доказательства</h3>'
 '<p>Фото и видео принимаются только с этих сервисов: <strong>YouTube, Rutube, Google Drive, Yandex Disk, imgur, Yapx, Prnt, ibb</strong>.</p>'
 '<p>Фиксация должна исчерпывающе подтверждать выполнение требования.</p>'
 '<div class="note bad"><div class="h">За что отклоняют чаще всего</div>'
 'Обрезанный или отредактированный скриншот · нет бодикамеры с красным индикатором · доклад в <code>/fb</code> вместо <code>/f</code> · '
 'сокращённое имя вроде «Лёха» вместо «Алексей» · скриншот чужого Discord вместо своей фракции · нарушена форма отчёта.</div>')

ru = dochead("du_", "Путь курсанта", "Система повышения",
             "Открыл — и сразу видно, что делать. Десять задач до 3 ранга, потом выбор подразделения. "
             "Под каждой задачей написано, что именно приложить в отчёт.",
             ["<b>5 задач</b> на ранг 1 → 2", "<b>5 задач</b> на ранг 2 → 3", "Военный билет с <b>6 ранга</b>"]) + \
     ROUTE + STAGE12 + STAGE23 + SUBMIT + AFTER + PROOFS

# ---------- памятка и экзамен (стабильные исходники) ----------
memo_raw = io.open(os.path.join(SRCDIR, "memo_src.html"), encoding="utf-8").read()
memo_raw = memo_raw.replace("<!--STROY-->", "")
exam_raw = io.open(os.path.join(SRCDIR, "exam_src.html"), encoding="utf-8").read()
memo = ('<div class="dochead dv"><div class="abbr">Обязательный минимум</div><h2>Памятка курсанта</h2>'
        '<p class="sub">То, что обязан знать наизусть каждый. По этому материалу проводится экзамен по внутренним НПА на этапе повышения 2 → 3.</p>'
        '<div class="facts"><span>12 разделов</span><span>Отметки <b>«Выучил»</b> сохраняются</span><span>Доклады копируются в один клик</span></div></div>'
        + memo_raw)
exam = ('<div class="dochead dd"><div class="abbr">Проверка знаний</div><h2>Вопросы к экзамену</h2>'
        '<p class="sub">Двадцать вопросов по всем разделам. Сначала ответь вслух, потом раскрывай ответ.</p>'
        '<div class="facts"><span>Раскрыто <b id="opened">0</b> из 20</span></div></div>' + exam_raw)


# ---------- кодексы РО ----------
Z = os.path.join(ROOT, "правовая", "законы")
ug_body = parse_code(os.path.join(Z, "уголовный-кодекс.md"), "ug")
ap_body = parse_code(os.path.join(Z, "коап-ро.md"), "ap")

ug = dochead("dc", "Законы РО", "Уголовный кодекс",
             "Преступления и наказания: что грозит нарушителю и по какой статье его задерживают. "
             "Звёздами отмечен приоритет розыска \u2014 один приоритет равен 10 месяцам лишения свободы (ст. 100.1).",
             ["%d статей" % ug_body.count('class="art"'), "8 разделов",
              "Раздел VIII \u2014 <b>против военной службы</b>"]) + ug_body

ap = dochead("da", "Законы РО", "Кодекс об административных правонарушениях",
             "Проступки, за которые не сажают: штрафы, предупреждения и порядок производства по делу. "
             "Сюда попадают мелкое хулиганство, неповиновение и оскорбление.",
             ["%d статей" % ap_body.count('class="art"'), "18 глав",
              "Оскорбление \u2014 <b>ст. 5.4</b>"]) + ap_body

tpl = io.open(TPL, encoding="utf-8").read()
tpl = tpl.replace("<!--PANE:MEMO-->", '<div class="pane" id="p-memo">%s</div>' % chanlinks(memo))
tpl = tpl.replace("<!--PANE:EXAM-->", '<div class="pane" id="p-ex" hidden>%s</div>' % chanlinks(exam))
for k, v in (("vu", vu), ("du", du), ("uk", uk), ("le", le), ("ru", ru), ("ug", ug), ("ap", ap)):
    tpl = tpl.replace("<!--INSERT:%s-->" % k, chanlinks(v))

# адрес воркера-помощника: пока файла нет — кнопка на странице не появляется
AIF = os.path.join(SRCDIR, "ai_url.txt")
ai_url = ""
if os.path.exists(AIF):
    ai_url = io.open(AIF, encoding="utf-8").read().strip()
if ai_url:
    tpl = tpl.replace('var AI_URL = "";', 'var AI_URL = "%s";' % ai_url)

io.open(OUT, "w", encoding="utf-8").write(tpl)

# standalone
head = ('<!DOCTYPE html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="description" content="База знаний ФСВНГ: памятка курсанта, уставы, лекции, правила и экзамен.">\n'
        '<style>html{color-scheme:light dark}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n')
i = tpl.find("</style>") + len("</style>")
alone = head + tpl[:i] + "\n</head>\n<body>\n" + tpl[i:] + "\n</body>\n</html>\n"
io.open(os.path.join(DIST, "памятка-курсанта_файл.html"), "w", encoding="utf-8").write(alone)

arts = tpl.count('class="art"')
print("OK  articles:%d  size:%dKB  standalone:%dKB" % (arts, len(tpl.encode())//1024, len(alone.encode())//1024))

# ---------- копия в корень проекта для GitHub Pages ----------
io.open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(alone)
print("index.html в корне обновлён")

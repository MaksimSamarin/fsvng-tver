# -*- coding: utf-8 -*-
"""Проверка целостности базы и собранного сайта. Запуск: python сайт/check.py"""
import io, os, re, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC  = os.path.join(ROOT, "правовая", "источники")
SITE = os.path.join(HERE, "dist", "памятка-курсанта.html")

log, errors, warns = [], 0, 0
def ok(m):   log.append("  OK   " + m)
def err(m):
    global errors; errors += 1; log.append("  ОШИБКА " + m)
def warn(m):
    global warns; warns += 1; log.append("  ! " + m)
def head(m): log.append("\n=== " + m + " ===")

def read(p): return io.open(p, encoding="utf-8-sig").read()
def arts(t): return re.findall(r"^\*{0,2}Статья\s+([0-9]+(?:\.[0-9]+)*)", t, re.M)

site = read(SITE)

# 1. уставы: все статьи оригинала есть на сайте
head("Статьи уставов: оригинал → сайт")
CH = [("устав-вс-и-фсвнг_оригинал.txt", "vu", "Устав ВС"),
      ("дисциплинарный-устав_оригинал.txt", "du", "Дисциплинарный"),
      ("устав-караульно-постовой-службы_оригинал.txt", "uk", "Караульный")]
total_src = 0
for fn, pref, name in CH:
    src = arts(read(os.path.join(SRC, fn)))
    total_src += len(src)
    miss = [a for a in src if ('id="%s-a%s"' % (pref, a.replace(".", "-"))) not in site]
    dup = [a for a in set(src) if src.count(a) > 1]
    if miss: err("%s: не попали на сайт статьи %s" % (name, ", ".join(miss)))
    else: ok("%s — все %d статей на месте" % (name, len(src)))
    if dup: warn("%s: повторы номеров в оригинале — %s" % (name, ", ".join(dup)))
site_arts = site.count('class="art"')
if site_arts == total_src: ok("на сайте ровно %d статей, лишних нет" % site_arts)
else: err("на сайте %d статей, в оригиналах %d" % (site_arts, total_src))

# 2. ссылки на статьи в markdown-базе
head("Ссылки на статьи в документах базы")
pools = {}
for fn, pref, name in CH:
    key = {"vu": "Устава ВС", "du": "ДУ", "uk": "УКПС"}[pref]
    pools[key] = set(arts(read(os.path.join(SRC, fn))))
# части внутри статей (18.1 и т.п.) тоже считаем валидными
for fn, pref in (("устав-караульно-постовой-службы_оригинал.txt", "УКПС"),):
    t = read(os.path.join(SRC, fn))
    pools[pref] |= set(re.findall(r"\b(\d+\.\d+)\s", t))
bad = []
for f in [x for x in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True) if "источники" not in x]:
    s = read(f)
    for m in re.finditer(r"ст\.\s*([0-9]+(?:\.[0-9]+)*)\s*(УКПС|ДУ|Устава ВС)", s):
        if m.group(1) not in pools[m.group(2)]:
            bad.append((os.path.relpath(f, ROOT), m.group(2), m.group(1)))
    for m in re.finditer(r"(УКПС|ДУ),?\s*ст\.\s*([0-9]+(?:\.[0-9]+)*)", s):
        if m.group(2) not in pools[m.group(1)]:
            bad.append((os.path.relpath(f, ROOT), m.group(1), m.group(2)))
if bad:
    for f, d, n in bad: err("%s → ст. %s %s не существует" % (f, n, d))
else: ok("все ссылки на статьи ведут в существующие нормы")

# 3. внутренние ссылки между файлами базы
head("Внутренние ссылки между документами")
broken = []
for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
    base = os.path.dirname(f)
    for m in re.finditer(r"\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]*)?\)", read(f)):
        t = os.path.normpath(os.path.join(base, m.group(1)))
        if not os.path.exists(t):
            broken.append("%s → %s" % (os.path.relpath(f, ROOT), m.group(1)))
if broken:
    for b in broken: err("битая ссылка: " + b)
else: ok("все ссылки между документами рабочие")

# 4. изображения
head("Изображения")
ph = json.loads(read(os.path.join(HERE, "исходники", "photos.json")))
used = [k for k in ph if ph[k][-120:] in site]   # хвост base64 уникален, префикс — нет
unused = [k for k in ph if k not in used]
imgs = site.count("<img ")
ok("в photos.json %d изображений, на сайте %d тегов img" % (len(ph), imgs))
if unused: warn("не использованы: %s" % ", ".join(sorted(unused)))
if site.count('src=""') or "src=\"\"" in site: err("есть пустые src у картинок")

# 5. структура сайта
head("Структура страницы")
for pid, nm in [("p-memo","Памятка"),("p-vu","Устав ВС"),("p-du","Дисциплинарный"),
                ("p-uk","Караульный"),("p-le","Лекции"),("p-ru","Повышение"),("p-ex","Экзамен")]:
    if 'id="%s"' % pid in site: ok("вкладка «%s» на месте" % nm)
    else: err("нет вкладки «%s»" % nm)
for cnt, need, what in [(site.count('class="blk"'), 12, "разделов памятки"),
                        (site.count('<details class="q">'), 20, "вопросов экзамена"),
                        (site.count('class="task"'), 10, "задач повышения"),
                        (site.count('class="chan '), 3, "карточек каналов в памятке"),
                        (site.count('class="st2"'), 2, "шага подачи отчёта")]:
    if cnt == need: ok("%d %s" % (cnt, what))
    else: err("%s: %d вместо %d" % (what, cnt, need))


# 5b. баланс тегов в панелях — ловит «уехавшие» блоки
head("Целостность панелей")
panes=["p-memo","p-ru","p-le","p-vu","p-du","p-uk","p-ex"]
diffs={}
for pid in panes:
    i=site.find('id="%s"'%pid); j=site.find('<div class="pane"', i+20)
    part=site[i:(j if j>0 else len(site))]
    diffs[pid]=part.count("<div")-part.count("</div>")
base=diffs["p-memo"]
skew=[p for p in panes[:-1] if diffs[p]!=base]
if skew: err("перекос тегов в панелях: %s — блок мог уехать в соседнюю вкладку" % ", ".join(skew))
else: ok("теги в панелях сбалансированы, блоки не перетекают")
for name,expect in [("Форма на присягу","p-le"),('id="dress"',"p-le"),('id="posts-vch"',"p-le"),("Как подать отчёт","p-ru")]:
    pos=site.find(name); found=None
    for pid in panes:
        i=site.find('id="%s"'%pid)
        if 0<i<pos: found=pid
    if found==expect: ok("«%s» в правильной вкладке" % name)
    else: warn("«%s» найден в %s, ожидалось %s" % (name, found, expect))


# 5c. якоря переходов между вкладками
head("Ссылки-переходы между вкладками")
anchors = re.findall(r'data-anchor="([^"]+)"', site)
dead = [a for a in set(anchors) if ('id="%s"' % a) not in site]
if dead: err("битые якоря переходов: %s" % ", ".join(sorted(dead)))
else: ok("все %d переходов ведут в существующие разделы" % len(anchors))

# 6. мусор и следы
head("Мусор и служебные следы")
for pat, desc in [("](", "необработанные markdown-ссылки"), ("**", "необработанный markdown"),
                  ("<!--INSERT", "незаменённые маркеры"), ("<!--PANE", "незаменённые маркеры"),
                  ("<!--STROY", "незаменённый маркер схем"), ("Инст.ОМОН", "авторская шапка"),
                  ("27564", "авторская шапка"), (">Режимный объект:<", "обрывок текста"),
                  ("Что изменилось", "упоминание прошлой редакции"), ("вне ВЧ", "устаревшая формулировка бодикамеры"),
                  ("Примечания к исходному", "редакторский блок"),
                  ("копипаста", "редакторский комментарий"),
                  ("PD, FIB", "артефакт англоязычного шаблона")]:
    n = site.count(pat)
    if n: err("%s: %d вхождений (%s)" % (desc, n, pat))
if not errors or True: ok("проверка мусора завершена")

# 7. ключевые факты: сайт vs оригиналы
head("Сверка ключевых фактов с оригиналами")
vu = read(os.path.join(SRC, "устав-вс-и-фсвнг_оригинал.txt"))
du = read(os.path.join(SRC, "дисциплинарный-устав_оригинал.txt"))
uk = read(os.path.join(SRC, "устав-караульно-постовой-службы_оригинал.txt"))
facts = [
 ("Код-4 — боевая тревога", "Код-4 - боевую тревогу" in vu, "Код-4" in site and "оевая тревога" in site),
 ("служебный день 11:00–21:30", "с 11:00 до 21:30" in vu, "11:00 – 21:30" in site or "11:00–21:30" in site),
 ("вечерняя проверка 21:00", "в 21:00 проводится вечерняя проверка" in vu, "21:00" in site),
 ("три активных выговора — увольнение", "трёх активных выговоров" in du, "Три активных выговора" in site),
 ("отработка выговора 48 часов", "48 часов" in du, "48 часов" in site),
 ("ФСВНГ ведёт ОСБ", "ОСБ работает по нарушениям только внутри подразделений ФСВНГ" in du, "ОСБ" in site),
 ("три поста на Алабино", "наблюдательная вышка" in uk.lower(), "Наблюдательная вышка" in site),
 ("запреты на КПП — ст. 36 УКПС", "Статья 36." in uk, "uk-a36" in site),
 ("режимный объект — ст. 37 УКПС", "Статья 37." in uk, "uk-a37" in site),
]
for name, in_src, in_site in facts:
    if in_src and in_site: ok(name)
    elif not in_src: err("%s — нет в оригинале устава" % name)
    else: err("%s — потерялось на сайте" % name)

# 8. файлы проекта
head("Файлы проекта")
for p in ["README.md", "ИСТОЧНИКИ.md", "профиль.md", "сайт/README.md", "сайт/build.py",
          "сайт/dist/памятка-курсанта.html", "сайт/dist/памятка-курсанта_файл.html"]:
    if os.path.exists(os.path.join(ROOT, p)): ok(p)
    else: err("нет файла " + p)

size = os.path.getsize(SITE) / 1048576
ok("размер страницы %.1f МБ" % size)
if size > 15: err("страница больше лимита 16 МБ")

log.append("\n" + "=" * 46)
log.append("ИТОГО: ошибок %d, предупреждений %d" % (errors, warns))
io.open(os.path.join(HERE, "check_report.txt"), "w", encoding="utf-8").write("\n".join(log))
print("report written")

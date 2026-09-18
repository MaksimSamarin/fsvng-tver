# -*- coding: utf-8 -*-
"""Собирает базу знаний для ИИ-помощника → kb.js (встраивается в воркер).
Запуск: python сайт/помощник/kb.py"""
import io, os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC  = os.path.join(ROOT, "правовая", "источники")
DOCS = os.path.join(ROOT, "docs")

def read(p): return io.open(p, encoding="utf-8-sig").read()

chunks = []

MAXLEN = 1600          # длинные статьи режем, иначе восемь фрагментов раздувают запрос

PLACEHOLDER = re.compile(r"\b[A-Z]{3,}(?:-[A-Z]+)+\b")   # технические маркеры сборки вроде OATH-UNIFORM-GALLERY

def add(doc, title, text, ref=""):
    text = re.sub(r"\s+", " ", PLACEHOLDER.sub("", text)).strip()
    if len(text) < 40: return
    if len(text) > MAXLEN: text = text[:MAXLEN].rsplit(" ", 1)[0] + "…"
    chunks.append({"d": doc, "t": title, "x": text, "r": ref})

# ---------- уставы: каждая статья отдельным фрагментом ----------
CHARTERS = [
    ("устав-вс-и-фсвнг_оригинал.txt", "Устав ВС и ФСВНГ", "ВУ"),
    ("дисциплинарный-устав_оригинал.txt", "Дисциплинарный устав", "ДУ"),
    ("устав-караульно-постовой-службы_оригинал.txt", "Устав караульно-постовой службы", "УКПС"),
]
for fn, doc, abbr in CHARTERS:
    lines = [l.strip() for l in read(os.path.join(SRC, fn)).split("\n")]
    num = title = None
    body = []
    def flush():
        if num:
            add(doc, "Статья %s%s" % (num, (". " + title) if title else ""),
                " ".join(body), "%s ст. %s" % (abbr, num))
    for l in lines:
        if not l or l.startswith("[") and l.endswith("]"): continue
        m = re.match(r"^\*{0,2}Статья\s+([0-9]+(?:\.[0-9]+)*)\.?\s*(.*?)\*{0,2}$", l)
        if m:
            flush()
            num, title, body = m.group(1), re.sub(r"\*", "", m.group(2)).strip(), []
            continue
        if re.match(r"^\*{0,2}(ГЛАВА|Глава)\b", l): continue
        if num: body.append(re.sub(r"\*\*(.+?)\*\*", r"\1", l))
    flush()

# ---------- кодексы РО: каждая статья отдельным фрагментом ----------
ZAK = os.path.join(ROOT, "правовая", "законы")
CODES = [
    ("уголовный-кодекс.md", "Уголовный кодекс РО", "УК"),
    ("коап-ро.md", "КоАП РО", "КоАП"),
]
CODE_JUNK = re.compile(r"^(Источник:|#|РАЗДЕЛ\s|Глава\s|УГОЛОВНЫЙ КОДЕКС|КОДЕКС РО|ОБ АДМИНИСТРАТИВНЫХ|\*)")
for fn, doc, abbr in CODES:
    p = os.path.join(ZAK, fn)
    if not os.path.exists(p): continue
    raw = read(p).replace("**", "")
    num = title = None
    body = []
    def flush_code():
        if num:
            add(doc, "Статья %s%s" % (num, (". " + title) if title else ""),
                " ".join(body), "%s ст. %s" % (abbr, num))
    for l in raw.split("\n"):
        l = l.strip()
        if not l or l.startswith("---"): continue
        m = re.match(r"^Статья\s+([0-9]+(?:\.[0-9]+)*)\.?\s*(.*)$", l)
        if m:
            flush_code()
            num, title, body = m.group(1), m.group(2).strip(), []
            continue
        if CODE_JUNK.match(l): continue
        if num: body.append(l)
    flush_code()

# ---------- лекции, правила, процедуры: по разделам ----------
MD = [
    ("лекция-постовая-служба.md", "Лекция «Постовая служба»"),
    ("лекция-субординация.md", "Лекция по субординации"),
    ("лекция-строевая-подготовка.md", "Лекция «Строевая подготовка»"),
    ("присяга.md", "Принятие присяги"),
    ("система-повышения.md", "Система повышения"),
    ("частые-ошибки.md", "Частые ошибки в отчётах"),
    ("требования-к-доказательствам.md", "Требования к доказательствам"),
]
SKIP = re.compile(r"(примечан|расхожден|исходному тексту|открытые вопрос)", re.I)
for fn, doc in MD:
    p = os.path.join(DOCS, fn)
    if not os.path.exists(p): continue
    sec, buf = "Общее", []
    for l in read(p).split("\n"):
        s = l.strip()
        m = re.match(r"^(#{2,4})\s+(.*)$", s)
        if m:
            # источник — название документа: иначе модели нечего указать в «Основании» по лекциям
            if not SKIP.search(sec): add(doc, sec, " ".join(buf), doc)
            sec, buf = m.group(2), []
            continue
        if s.startswith("|") or s.startswith("---"):
            s = s.strip("|").replace("|", " — ")
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s).replace("`", "")
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        if s and not set(s) <= set("- :—"): buf.append(s)
    if not SKIP.search(sec): add(doc, sec, " ".join(buf), doc)

out = os.path.join(HERE, "kb.js")
io.open(out, "w", encoding="utf-8").write(
    "// Сгенерировано kb.py — не править руками\nexport const KB = " +
    json.dumps(chunks, ensure_ascii=False, separators=(",", ":")) + ";\n")
size = os.path.getsize(out) / 1024
print("фрагментов: %d | kb.js: %.0f KB" % (len(chunks), size))
for d in sorted(set(c["d"] for c in chunks)):
    print("   %-36s %d" % (d, sum(1 for c in chunks if c["d"] == d)))

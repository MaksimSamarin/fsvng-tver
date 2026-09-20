# -*- coding: utf-8 -*-
"""Скачивает действующие редакции уставов из Google Docs и кладёт их в правовая/источники/*_оригинал.txt.

    python обновить-уставы.py            скачать, показать, что изменилось, записать
    python обновить-уставы.py --check    только сравнить с базой, ничего не писать

После обновления: python сайт/build.py → python сайт/check.py → python сайт/помощник/kb.py → node сайт/помощник/test.mjs,
затем пересчёт векторов на реле и деплой воркера (см. сайт/помощник/README.md). Конспекты в правовая/*.md и фразы
помощника (keys.json) скрипт не трогает — сверить руками по списку новых и исчезнувших статей."""
import io, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "правовая", "источники")

# документ → id Google Docs (ссылка вида https://docs.google.com/document/d/<id>/edit)
DOCS = [
    ("устав-вс-и-фсвнг", "11ehdtec25LJwBUFovFq9RR-_4CdQZiN_8xWHfyYNe3A", "Устав ВС и ФСВНГ"),
    ("дисциплинарный-устав", "1BLHWZ-aMoFVMmwuJgOOyJ10gPK9IfLi2wMsSHAKD9ss", "Дисциплинарный устав"),
    ("устав-караульно-постовой-службы", "1S6apc4hqrn7BXSmngqVgtHLDip6zip6rq7RVub6bkA0", "Устав караульно-постовой службы"),
]
EXPORT = "https://docs.google.com/document/d/%s/export?format=txt"
ART = re.compile(r"^Статья\s+([0-9]+(?:\.[0-9]+)*)")


def fetch(doc_id):
    req = urllib.request.Request(EXPORT % doc_id, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig")


def clean(text):
    """Убирает артефакты экспорта Google Docs, не трогая текст норм:
    маркеры списков «* », линейки «____», невидимые символы, продублированный заголовок статьи."""
    text = text.replace("\r", "").replace("​", "").replace("﻿", "").replace("\xa0", " ")
    out, prev_title, blank = [], None, False
    for raw in text.split("\n"):
        l = raw.strip()
        l = re.sub(r"^\*\s+", "- ", l)            # маркер списка Google Docs → «- », как в старых оригиналах
        if l.startswith("- Статья "):
            l = l[2:]                             # маркер прилип к заголовку статьи («* Статья 6.1.»)
        l = re.sub(r"\s{2,}", " ", l)
        if not l or set(l) <= set("_ "):
            if out and not blank:
                out.append(""); blank = True
            continue
        m = re.match(r"^Статья\s+[0-9.]+\.?\s*(.*)$", l)
        if m:
            prev_title = m.group(1).strip() or None
        elif prev_title:
            if l == prev_title:                   # название статьи повторено строкой ниже
                continue
            if l.startswith(prev_title + " "):    # название статьи прилипло к первому абзацу
                l = l[len(prev_title) + 1:]
            prev_title = None
        out.append(l); blank = False
    return "\n".join(out).strip() + "\n"


def arts(text):
    return [m.group(1) for m in (ART.match(l) for l in text.split("\n")) if m]


def main():
    check = "--check" in sys.argv
    changed = 0
    for name, doc_id, title in DOCS:
        path = os.path.join(DST, name + "_оригинал.txt")
        new = clean(fetch(doc_id))
        old = io.open(path, encoding="utf-8-sig").read().replace("\r", "") if os.path.exists(path) else ""
        oa, na = arts(old), arts(new)
        head = new.split("\n")[1] if "\n" in new else ""
        if old.strip() == new.strip():
            print("%-32s без изменений (%d статей)" % (title, len(na)))
            continue
        changed += 1
        print("%-32s ИЗМЕНЁН: статей %d → %d · %s" % (title, len(oa), len(na), head))
        added = [a for a in na if a not in oa]
        gone = [a for a in oa if a not in na]
        if added: print("   новые статьи:    " + ", ".join(added))
        if gone:  print("   исчезли статьи:  " + ", ".join(gone))
        if not check:
            io.open(path, "w", encoding="utf-8", newline="\n").write(new)
            print("   записан " + os.path.relpath(path, HERE))
    if changed and not check:
        print("\nдальше: python сайт/build.py → python сайт/check.py → python сайт/помощник/kb.py → node сайт/помощник/test.mjs → векторы на реле → деплой")
    return 0


if __name__ == "__main__":
    sys.exit(main())

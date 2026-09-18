# -*- coding: utf-8 -*-
"""Сжимает фото и кодирует в data:URI → photos.json"""
import io, os, json, base64
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), "Фото")
DOCPOSTS = os.path.join(HERE, "исходники", "посты-вч")
OUT = os.path.join(HERE, "исходники", "photos.json")

def enc(path, width, q=80):
    im = Image.open(path)
    if im.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", im.size, (237, 234, 227))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
    b = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(b).decode(), len(b)

photos, total = {}, 0

# посты
POSTS = {
    "kpp1": "КПП №1 Алабино - ДВА ВОЕННОСЛУЖАЩИХ СЛЕВА И СПРАВА ОТ ВОРОТ, ОДИН ЗА ВОРОТАМИ",
    "kpp2": "КПП №2 Алабино - ДВА ВОЕННОСЛУЖАЩИХ СЛЕВА И СПРАВА ОТ ШЛАГБАУМА, ОДИН ЗА ШЛАГБАУМОМ",
    "tower": "Наблюдательная вышка Алабино - ДВА ВОЕННОСЛУЖАЩИХ",
    "oruj": "Вышка Оружейки -  ОДИН ВОЕННОСЛУЖАЩИЙ",
    "ogn": "Вышка Огневой рубеж -  ОДИН ВОЕННОСЛУЖАЩИЙ",
    "lager": "Вышка Лагерь -  ОДИН ВОЕННОСЛУЖАЩИЙ",
}
base = os.path.join(ROOT, "Посты Алабино")
for key, folder in POSTS.items():
    d = os.path.join(base, folder)
    if not os.path.isdir(d):
        print("НЕТ ПАПКИ:", folder); continue
    for f in os.listdir(d):
        p = os.path.join(d, f)
        low = f.lower()
        if low.startswith("фото"):
            photos["post-%s-photo" % key], n = enc(p, 800, 75)
        elif low.startswith("метка"):
            photos["post-%s-map" % key], n = enc(p, 660, 75)
        else:
            continue
        total += n

# дресс-код
DRESS = {
    "akad-m": ("Академия ФСВНГ (муж).jpg", None),
    "akad-w": ("Академия ФСВНГ (жен).png", None),
    "omon":   ("ОМОН ФСВНГ.png", None),
    "osb":    ("ОСБ ФСВНГ.png", None),
    "rvo":    ("РВО ФСВНГ.jpg", None),
    "parad-m": ("Начальство ФСВНГ, Кадровая служба ФСВНГ, Парадная ФСВНГ", "мужское.png"),
    "parad-w": ("Начальство ФСВНГ, Кадровая служба ФСВНГ, Парадная ФСВНГ", "женское.png"),
    "oath-off": ("Присяга", "Форма старшего офицера.png"),
    "oath-cadet": ("Присяга", "Форма дающего присягу.png"),
}
dbase = os.path.join(ROOT, "Дресс-код ФСВНГ")
for key, (a, b) in DRESS.items():
    p = os.path.join(dbase, a, b) if b else os.path.join(dbase, a)
    if not os.path.exists(p):
        print("НЕТ ФАЙЛА:", p); continue
    photos["dress-" + key], n = enc(p, 780, 78)
    total += n

# строевая — схемы перерисованы векторно в build.py, фото не нужны
sbase = os.path.join(ROOT, "Строевая подготовка")
for f in []:  # sorted(os.listdir(sbase))
    if f.lower().endswith((".png", ".jpg", ".jpeg")):
        k = "stroy-" + os.path.splitext(f)[0]
        photos[k], n = enc(os.path.join(sbase, f), 900, 82)
        total += n

io.open(OUT, "w", encoding="utf-8").write(json.dumps(photos, ensure_ascii=False))
print("изображений: %d | суммарно: %.1f MB | json: %.1f MB"
      % (len(photos), total/1048576, os.path.getsize(OUT)/1048576))
for k in sorted(photos): print("  ", k, "%.0fKB" % (len(photos[k])*0.75/1024))

# ---------- посты воинской части (из Google Docs) ----------
VCH = [
    ("vch-kpp1",  DOCPOSTS + "/image1.png"),
    ("vch-kpp2",  DOCPOSTS + "/image3.png"),
    ("vch-avto",  DOCPOSTS + "/image8.png"),
    ("vch-vkpp1", DOCPOSTS + "/image4.png"),
    ("vch-bober", DOCPOSTS + "/image2.png"),
    ("vch-tyl",   DOCPOSTS + "/image5.png"),
    ("vch-ap1",   DOCPOSTS + "/image6.png"),
    ("vch-ap2",   DOCPOSTS + "/image7.png"),
]
add = 0
for key, path in VCH:
    if not os.path.exists(path):
        print("НЕТ:", path); continue
    photos[key], n = enc(path, 820, 75)
    add += n
io.open(OUT, "w", encoding="utf-8").write(json.dumps(photos, ensure_ascii=False))
print("посты ВЧ: %d шт, +%.1f MB | всего изображений: %d | json: %.1f MB"
      % (len(VCH), add/1048576, len(photos), os.path.getsize(OUT)/1048576))

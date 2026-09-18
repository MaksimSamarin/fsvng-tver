# -*- coding: utf-8 -*-
"""Считает векторы всех фрагментов базы через реле → kb-vec.js.
Запуск на машине, которой реле открыто (порт пускает только сети Cloudflare, поэтому
обычно — на самом сервере реле):
    RELAY_URL=https://127.0.0.1:8443/api/embed RELAY_SECRET=... RELAY_INSECURE=1 python3 vec.py
Пересчитывать после любой правки уставов, лекций или смены модели эмбеддингов."""
import base64, hashlib, io, json, math, os, re, ssl, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KB_JS = os.path.join(HERE, "kb.js")
OUT = os.path.join(HERE, "kb-vec.js")
URL = os.environ.get("RELAY_URL", "")
SECRET = os.environ.get("RELAY_SECRET", "")
BATCH = 40

if not URL or not SECRET:
    sys.exit("нужны RELAY_URL и RELAY_SECRET")

raw = io.open(KB_JS, encoding="utf-8").read()
kb = json.loads(raw[raw.index("[", raw.index("export const KB")):raw.rindex("]") + 1])
# в вектор идёт только текст источника — разговорные фразы (k) остаются в поиске по словам
texts = [(c["t"] + ". " + c["x"]).strip() for c in kb]
sig = hashlib.sha1("\n".join(c.get("r", "") + "|" + c["t"] for c in kb).encode("utf-8")).hexdigest()[:16]

ctx = ssl.create_default_context()
if os.environ.get("RELAY_INSECURE") == "1":          # только для 127.0.0.1 на самом сервере
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE


def call(items):
    req = urllib.request.Request(URL, data=json.dumps({"input": items}, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Relay-Key": SECRET})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


vectors, model, dims = [], None, None
t0 = time.time()
for i in range(0, len(texts), BATCH):
    d = call(texts[i:i + BATCH])
    model = d["model"]
    dims = d["dims"]
    vectors.extend(d["vectors"])
    print("  %d/%d" % (min(i + BATCH, len(texts)), len(texts)), flush=True)
    time.sleep(0.5)                                    # реле пускает 20 запросов в минуту с адреса

assert len(vectors) == len(kb), "число векторов не совпало с числом фрагментов"
assert all(len(v) == dims for v in vectors), "разная размерность"

# нормируем и квантуем в int8: dot(int8, unit_q) / 127 ≈ cos
buf = bytearray()
for v in vectors:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    for x in v:
        q = int(round(x / n * 127))
        buf.append((max(-127, min(127, q))) & 0xFF)

js = ("// Сгенерировано vec.py — не править руками. Векторы статей для гибридного поиска.\n"
      "// Модель зафиксирована: вопрос курсанта должен считаться той же моделью в той же размерности.\n"
      "export const VEC = " + json.dumps({"model": model, "dims": dims, "n": len(kb), "sig": sig,
                                          "data": base64.b64encode(bytes(buf)).decode("ascii")}) + ";\n")
io.open(OUT, "w", encoding="utf-8").write(js)
print("готово: %d векторов × %d, модель %s, %.0f КБ, %.0fс" % (len(kb), dims, model, len(js) / 1024, time.time() - t0))

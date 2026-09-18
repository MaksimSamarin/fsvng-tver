# -*- coding: utf-8 -*-
"""Калибровка порогов векторного поиска: косинусы контрольных вопросов к статьям.
Запуск там же, где vec.py (реле должно быть доступно):
    RELAY_URL=https://127.0.0.1:8443/api/embed RELAY_SECRET=... RELAY_INSECURE=1 python3 vec_check.py"""
import base64, io, json, math, os, ssl, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL, SECRET = os.environ.get("RELAY_URL", ""), os.environ.get("RELAY_SECRET", "")
if not URL or not SECRET:
    sys.exit("нужны RELAY_URL и RELAY_SECRET")

raw = io.open(os.path.join(HERE, "kb.js"), encoding="utf-8").read()
kb = json.loads(raw[raw.index("[", raw.index("export const KB")):raw.rindex("]") + 1])
vraw = io.open(os.path.join(HERE, "kb-vec.js"), encoding="utf-8").read()
vec = json.loads(vraw[vraw.index("{", vraw.index("export const VEC")):vraw.rindex("}") + 1])
D, N = vec["dims"], vec["n"]
buf = base64.b64decode(vec["data"])
mat = [[(b - 256 if b > 127 else b) / 127.0 for b in buf[i * D:(i + 1) * D]] for i in range(N)]

ctx = ssl.create_default_context()
if os.environ.get("RELAY_INSECURE") == "1":
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE


def embed(texts):
    req = urllib.request.Request(URL, data=json.dumps({"input": texts}, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Relay-Key": SECRET})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))["vectors"]


CASES = [
    ("на меня напали, что делать", ["ВУ ст. 5.4", "ВУ ст. 7.1.2"]),
    ("залипать в телефон на кпп", ["УКПС ст. 36", "УКПС ст. 29"]),
    ("можно курить на посту", ["УКПС ст. 36"]),
    ("что будет за угон военной машины", ["УК ст. 67"]),
    ("командир требует деньги за повышение", ["ДУ ст. 23", "УК ст. 86"]),
    ("куда везти задержанного", ["ВУ ст. 5.3", "Лекция «Постовая служба»"]),
    ("какая форма на присягу", ["Принятие присяги"]),
    ("сколько выговоров до увольнения", ["ДУ ст. 6.1"]),
    ("чел на кпп быкует, чё делать", ["УКПС ст. 30", "УК ст. 105"]),
    ("как приготовить борщ", []),
    ("кто выиграл чемпионат", []),
    ("привет как дела", []),
]
qs = embed([q for q, _ in CASES])
for (q, want), v in zip(CASES, qs):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    v = [x / n for x in v]
    cos = [sum(a * b for a, b in zip(row, v)) for row in mat]
    order = sorted(range(N), key=lambda i: -cos[i])
    top = ["%s %.2f" % (kb[i].get("r") or kb[i]["t"][:20], cos[i]) for i in order[:3]]
    hit = max([cos[i] for i in range(N) if kb[i].get("r") in want] or [0])
    print("%-40s ждём %-28s max=%.2f | топ: %s" % (q, ("/".join(want) if want else "— отказ")[:28], hit, " ; ".join(top)))

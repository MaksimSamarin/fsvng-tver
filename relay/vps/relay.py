#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Реле помощника ФСВНГ на VPS: воркер Cloudflare → это реле → OpenRouter / Groq.

Только стандартная библиотека Python 3.12, никаких зависимостей.
Вход:  POST /api/chat  {messages:[...], max_tokens?:550, model?:"vendor/slug:free"}  + заголовок X-Relay-Key
Выход: {answer, model}  либо  {error, detail}

Защита: секрет в заголовке (сравнение постоянного времени), лимит запросов на адрес и общий,
тело не больше 64 КБ, единственный путь и метод, TLS с перечитыванием сертификата после продления.
Снаружи порт открыт только для сетей Cloudflare — это делает setup.sh через ufw.
"""
import hmac
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8443"))
SECRET = os.environ.get("RELAY_SECRET", "")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
PROVIDERS = [p.strip() for p in os.environ.get("PROVIDERS", "openrouter,groq").split(",") if p.strip()]
GROQ_MODELS = [m.strip() for m in os.environ.get("GROQ_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-120b").split(",") if m.strip()]
PAID_MODEL = os.environ.get("PAID_MODEL", "").strip()   # платная модель OpenRouter — самый последний рубеж, нужен баланс
# Эмбеддинги для поиска: одна модель навсегда — векторы статей и вопросов сравнимы только от одних весов.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen/qwen3-embedding-4b").strip()
EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "1024") or 0)
MAX_EMBED_ITEMS = 64
# Журнал вопросов (только текст и время, без адресов) — единственный честный источник для проверки поиска
LOG_QUESTIONS = os.environ.get("LOG_QUESTIONS", "1") == "1"
LOG_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/relay")
TLS_CERT = os.environ.get("TLS_CERT", "/etc/relay/tls/fullchain.pem")
TLS_KEY = os.environ.get("TLS_KEY", "/etc/relay/tls/privkey.pem")
MAX_BODY = 256 * 1024       # пачка статей на эмбеддинг не влезает в 64 КБ
RATE_IP, RATE_ALL = 20, 60          # запросов в минуту: с одного адреса / всего
UA = "fsvng-relay/1.0 (+https://maksimsamarin.github.io/fsvng-tver/)"

# Бесплатные модели OpenRouter в порядке предпочтения; точные id берутся из каталога.
# Прогон 18.09.2026 на одном промпте: DeepSeek — лучший формат (7 с), Nemotron — быстрее всех (2 с),
# Ling — быстро и по делу. Inkling отдаёт 403, Qwen3.8/Gemma 4/GLM 5.2 на бесплатном тарифе не отвечали.
PRIORITY = [r"deepseek.*v4.*flash", r"nemotron-3-super", r"ling-3.*flash"]


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# ---------- лимит запросов ----------
_lock = threading.Lock()
_hits = {}   # ip -> [время запросов за последнюю минуту]


def allowed(ip):
    now = time.time()
    with _lock:
        for k in list(_hits):
            _hits[k] = [t for t in _hits[k] if now - t < 60]
            if not _hits[k]:
                del _hits[k]
        total = sum(len(v) for v in _hits.values())
        if len(_hits.get(ip, [])) >= RATE_IP or total >= RATE_ALL:
            return False
        _hits.setdefault(ip, []).append(now)
        return True


# ---------- исходящие запросы ----------
def http_json(url, headers, body=None, timeout=45):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


_or_cache = {"at": 0.0, "ids": []}


def or_models():
    if _or_cache["ids"] and time.time() - _or_cache["at"] < 6 * 3600:
        return _or_cache["ids"]
    st, txt = http_json("https://openrouter.ai/api/v1/models", {"Authorization": "Bearer " + OR_KEY}, timeout=30)
    if st != 200:
        raise RuntimeError("каталог OpenRouter: HTTP %d" % st)
    free = [m.get("id", "") for m in json.loads(txt).get("data", []) if str(m.get("id", "")).endswith(":free")]
    ids = []
    for pat in PRIORITY:
        hit = next((i for i in free if re.search(pat, i, re.I)), None)
        if hit:
            ids.append(hit)
    _or_cache.update(at=time.time(), ids=ids)
    log("каталог OpenRouter: %d бесплатных, выбрано %d" % (len(free), len(ids)))
    return ids


def chat(url, key, model, messages, max_tokens, extra=None, reasoning_off=False):
    body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    if reasoning_off:
        # думающие модели тратят лимит токенов на рассуждения и отдают пустой content — просим не думать вслух
        body["reasoning"] = {"enabled": False, "exclude": True}
    st, txt = http_json(url, {"Authorization": "Bearer " + key, "Content-Type": "application/json", **(extra or {})}, body)
    if st != 200:
        return None, "%s: HTTP %d %s" % (model, st, txt[:120].replace("\n", " "))
    try:
        ans = (json.loads(txt)["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None, model + ": нечитаемый ответ"
    return (ans, None) if ans else (None, model + ": пустой ответ")


def ask(messages, max_tokens, want_model):
    errors = []
    for prov in PROVIDERS:
        if prov == "openrouter" and OR_KEY:
            try:
                ids = or_models()
            except Exception as e:
                errors.append(str(e))
                continue
            if want_model:
                ids = [want_model] + [i for i in ids if i != want_model]
            for m in ids:
                ans, err = chat("https://openrouter.ai/api/v1/chat/completions", OR_KEY, m, messages, max_tokens,
                                {"HTTP-Referer": "https://maksimsamarin.github.io/fsvng-tver/", "X-Title": "FSVNG assistant"},
                                reasoning_off=True)
                if ans:
                    return ans, "openrouter/" + m, errors
                errors.append(err)
        elif prov == "groq" and GROQ_KEY:
            for m in GROQ_MODELS:
                ans, err = chat("https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, m, messages, max_tokens)
                if ans:
                    return ans, "groq/" + m, errors
                errors.append(err)
    # всё бесплатное выбрано за день — платная модель за счёт баланса OpenRouter (~15 центов на тысячу вопросов)
    if PAID_MODEL and OR_KEY:
        ans, err = chat("https://openrouter.ai/api/v1/chat/completions", OR_KEY, PAID_MODEL, messages, max_tokens,
                        {"HTTP-Referer": "https://maksimsamarin.github.io/fsvng-tver/", "X-Title": "FSVNG assistant"},
                        reasoning_off=True)
        if ans:
            return ans, "openrouter-paid/" + PAID_MODEL, errors
        errors.append("платная " + err)
    return None, None, errors


def embed(items):
    if not OR_KEY:
        return None, "нет OPENROUTER_API_KEY"
    body = {"model": EMBED_MODEL, "input": items}
    if EMBED_DIMS:
        body["dimensions"] = EMBED_DIMS
    st, txt = http_json("https://openrouter.ai/api/v1/embeddings",
                        {"Authorization": "Bearer " + OR_KEY, "Content-Type": "application/json"}, body, timeout=60)
    if st != 200:
        return None, "%s: HTTP %d %s" % (EMBED_MODEL, st, txt[:120].replace("\n", " "))
    try:
        data = sorted(json.loads(txt)["data"], key=lambda x: x.get("index", 0))
        return [x["embedding"] for x in data], None
    except Exception:
        return None, "нечитаемый ответ эмбеддера"


_qlock = threading.Lock()


def log_question(q):
    """Только текст вопроса и время. Ни адреса, ни ответа."""
    try:
        line = json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "q": q.strip()[:600]}, ensure_ascii=False)
        with _qlock, open(os.path.join(LOG_DIR, "questions.jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        log("журнал вопросов недоступен: %s" % e)


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "relay"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):     # тела запросов в журнал не попадают — своё логирование
        pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._json(404, {"error": "not found"})

    def do_POST(self):
        ip = self.client_address[0]
        if self.path not in ("/api/chat", "/api/embed"):
            return self._json(404, {"error": "not found"})
        if not SECRET or not hmac.compare_digest(self.headers.get("X-Relay-Key", ""), SECRET):
            log("403 %s" % ip)
            return self._json(403, {"error": "forbidden"})
        if not allowed(ip):
            log("429 %s" % ip)
            return self._json(429, {"error": "слишком часто, подожди минуту"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {"error": "тело запроса пустое или больше 64 КБ"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "тело не JSON"})

        if self.path == "/api/embed":
            items = body.get("input")
            if (not isinstance(items, list) or not items or len(items) > MAX_EMBED_ITEMS
                    or not all(isinstance(x, str) and x.strip() for x in items)):
                return self._json(400, {"error": "input: список из 1–%d непустых строк" % MAX_EMBED_ITEMS})
            q = body.get("q")
            if LOG_QUESTIONS and isinstance(q, str) and q.strip():
                log_question(q)
            t0 = time.time()
            vecs, err = embed([x[:6000] for x in items])
            if vecs:
                log("emb %s %d шт. %.1fс" % (ip, len(vecs), time.time() - t0))
                return self._json(200, {"vectors": vecs, "model": EMBED_MODEL, "dims": len(vecs[0])})
            log("emb-502 %s %s" % (ip, err))
            return self._json(502, {"error": err})

        try:
            messages = body["messages"]
            assert isinstance(messages, list) and messages
        except Exception:
            return self._json(400, {"error": "нужно поле messages"})
        try:
            max_tokens = min(int(body.get("max_tokens") or 550), 1200)
        except (TypeError, ValueError):
            max_tokens = 550
        t0 = time.time()
        ans, via, errors = ask(messages, max_tokens, body.get("model"))
        if ans:
            log("200 %s via %s %.1fс%s" % (ip, via, time.time() - t0, (" после сбоев: " + "; ".join(errors)[:200]) if errors else ""))
            return self._json(200, {"answer": ans, "model": via})
        log("502 %s %s" % (ip, "; ".join(errors)[:300]))
        return self._json(502, {"error": "ни одна модель не ответила", "detail": errors[:6]})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # обрывы TLS-рукопожатия от сканеров — одна строка, без трейсбека
        log("сбой соединения %s: %s" % (client_address[0], sys.exc_info()[1]))


def make_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(TLS_CERT, TLS_KEY)
    return ctx


def cert_mtime():
    try:
        return max(os.stat(TLS_CERT).st_mtime, os.stat(TLS_KEY).st_mtime)
    except OSError:
        return 0


def watch_cert(ctx):
    """После продления сертификата таймер кладёт новые файлы — перечитываем без рестарта."""
    seen = cert_mtime()
    while True:
        time.sleep(600)
        m = cert_mtime()
        if m and m != seen:
            try:
                ctx.load_cert_chain(TLS_CERT, TLS_KEY)
                seen = m
                log("сертификат перечитан")
            except Exception as e:
                log("сертификат не перечитан: %s" % e)


def main():
    if not SECRET:
        log("RELAY_SECRET не задан — отказываюсь стартовать")
        sys.exit(1)
    if not OR_KEY and not GROQ_KEY:
        log("нет ни OPENROUTER_API_KEY, ни GROQ_API_KEY — отказываюсь стартовать")
        sys.exit(1)
    ctx = make_context()
    srv = Server(("0.0.0.0", PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=watch_cert, args=(ctx,), daemon=True).start()
    if LOG_QUESTIONS and not os.path.isdir(LOG_DIR):
        log("каталог журнала %s не существует — вопросы писаться не будут" % LOG_DIR)
    log("реле слушает :%d, провайдеры: %s%s" % (PORT, ", ".join(p for p in PROVIDERS if (p == "openrouter" and OR_KEY) or (p == "groq" and GROQ_KEY)),
                                              (", платный рубеж: " + PAID_MODEL) if PAID_MODEL and OR_KEY else ""))
    log("эмбеддинги: %s, %d измерений" % (EMBED_MODEL, EMBED_DIMS))
    srv.serve_forever()


if __name__ == "__main__":
    main()

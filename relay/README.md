# Реле для OpenRouter

Резервный путь помощника на случай, когда дневной лимит Workers AI исчерпан.

## Зачем отдельная площадка

OpenRouter гео-блокирует Россию. Воркер Cloudflare этого не обходит: его подзапросы уходят с адреса Cloudflare, но **страна посетителя передаётся дальше** — проверено через `cdn-cgi/trace`, `loc=RU`. Курсант из РФ жмёт кнопку → OpenRouter видит Россию → 403. Реле стоит на Vercel (США) и таких меток не несёт.

## Как работает

```
воркер ──POST {messages}, X-Relay-Key──▶ relay/api/chat.js ──▶ OpenRouter
```

Реле берёт из каталога OpenRouter бесплатные модели (`:free`) по списку предпочтений в `PRIORITY` и пробует по очереди, пока одна не ответит. Ключ OpenRouter лежит только здесь, в переменных окружения Vercel. Воркер знает адрес реле и общий секрет.

## Развернуть (один раз, ~5 минут)

1. `vercel.com` → войти через GitHub → **Add New → Project** → импортировать `MaksimSamarin/fsvng-tver`.
2. В настройках импорта: **Root Directory** → `relay`. Framework — Other.
3. **Environment Variables** — две штуки:
   - `OPENROUTER_API_KEY` — ключ с `openrouter.ai/keys` (тот же, что в `сайт/помощник/.dev.vars`)
   - `RELAY_SECRET` — значение из `сайт/помощник/.dev.vars`, строка `RELAY_SECRET=`
4. **Deploy**. Адрес будет вида `https://fsvng-tver-xxxx.vercel.app`; реле отвечает на `…/api/chat`.
5. Сообщить адрес — он прописывается в секрет воркера `RELAY_URL`:
   ```
   cd сайт/помощник
   echo https://fsvng-tver-xxxx.vercel.app/api/chat | npx wrangler secret put RELAY_URL
   ```
   `RELAY_SECRET` в воркер уже положен.

Дальше Vercel сам пересобирает реле при каждом пуше в `main`.

## Лимиты

У бесплатных моделей OpenRouter свой суточный потолок на аккаунт: **50 запросов в день**, если на счёте никогда не было $10, и **1000 в день** после разового пополнения на $10. Это отдельно от 10 000 нейронов Workers AI, так что резерв добавляет 50 ответов в день бесплатно — или 1000 за десять долларов один раз.

## Проверить

```
curl -X POST https://fsvng-tver-xxxx.vercel.app/api/chat \
  -H "Content-Type: application/json" -H "X-Relay-Key: <секрет>" \
  -d '{"messages":[{"role":"user","content":"Скажи «работает» одним словом"}]}'
```

Ответ `{"answer":"Работает.","model":"…:free"}` — реле живо. `403 forbidden` — не совпал секрет. `502` с `detail` — OpenRouter отбил все модели, текст ошибок внутри.

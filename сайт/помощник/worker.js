// Помощник по уставам ФСВНГ — Cloudflare Worker + Workers AI
// Модель крутится внутри Cloudflare: внешний Groq режет запросы с адресов воркеров (403 Forbidden).
import { KB } from "./kb.js";

const MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
const FALLBACK = "@cf/meta/llama-3.1-8b-instruct";
const TOP_K = 8;          // сколько фрагментов уставов подкладываем в запрос
const MAX_Q = 600;        // ограничение длины вопроса

const SYSTEM = `Ты — инструктор Кадровой службы ФСВНГ (Росгвардия) на RP-сервере «Тверской» в GTA 5 RP.
Отвечаешь курсантам, которые описывают игровую ситуацию и спрашивают, как действовать.

ПРАВИЛА ОТВЕТА:
1. Отвечай ТОЛЬКО на основании фрагментов уставов и правил, которые даны в запросе. Ничего не выдумывай.
2. Если во фрагментах нет ответа — так и скажи: «В уставах этого нет, уточни у старшего состава». Не додумывай.
3. Формат: сначала короткий вывод одной строкой, затем пронумерованный порядок действий (2–5 пунктов).
4. В конце строка «Основание:» — перечисли статьи из поля «источник» у фрагментов, которыми ты реально пользовался.
   Пиши их как в источнике, вместе с названием устава: «УКПС ст. 36, ДУ ст. 10». НИКОГДА не пиши номера фрагментов в квадратных скобках.
5. Пиши по-русски, коротко и по-военному чётко. Без воды, без вступлений вроде «конечно» и «давайте разберём».
6. Если в ситуации есть риск нарушения — предупреди отдельной строкой, что за это грозит.
7. Команды в игре приводи точно: /f — рация IC, /fb — OOC, /me и /do — отыгровка.`;

// --- грубая нормализация русского слова: отбрасываем окончание ---
function stem(w) {
  w = w.toLowerCase().replace(/ё/g, "е");
  return w.length > 5 ? w.slice(0, w.length - 2) : w;
}
function tokens(s) {
  return (s.toLowerCase().replace(/ё/g, "е").match(/[а-яa-z0-9]{3,}/gi) || []).map(stem);
}

// --- отбор релевантных фрагментов ---
const INDEX = KB.map((c) => ({ c, toks: new Set(tokens(c.t + " " + c.x)) }));

function pick(question) {
  const qt = tokens(question);
  const num = question.match(/\b\d+(?:\.\d+)?\b/g) || [];
  const scored = INDEX.map(({ c, toks }) => {
    let score = 0;
    for (const t of qt) if (toks.has(t)) score += 1;
    // прямое упоминание номера статьи весит больше
    for (const n of num) if (c.r && c.r.includes(" " + n)) score += 6;
    return { c, score };
  })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, TOP_K);
  return scored.map((x) => x.c);
}

// Чужим сайтам встраивать помощника незачем — лимиты аккаунта общие.
const ALLOW = [
  "https://maksimsamarin.github.io",
  "http://localhost:8080",
  "http://127.0.0.1:8080",
];
function allowed(origin) {
  return !origin || origin === "null" || ALLOW.includes(origin);
}

function cors(origin) {
  return {
    "Access-Control-Allow-Origin": allowed(origin) ? origin || "*" : "https://maksimsamarin.github.io",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

async function think(env, model, q, context) {
  const out = await env.AI.run(model, {
    temperature: 0.2,
    max_tokens: 700,
    messages: [
      { role: "system", content: SYSTEM },
      { role: "user", content: `ФРАГМЕНТЫ УСТАВОВ И ПРАВИЛ:\n\n${context}\n\n---\nСИТУАЦИЯ КУРСАНТА: ${q}` },
    ],
  });
  return (out.response || "").trim();
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin");
    if (request.method === "OPTIONS") return new Response(null, { headers: cors(origin) });

    if (request.method !== "POST")
      return new Response("Помощник ФСВНГ. Отправь POST {\"q\":\"вопрос\"}", {
        headers: { "Content-Type": "text/plain; charset=utf-8", ...cors(origin) },
      });

    if (!allowed(origin))
      return Response.json({ error: "Помощник работает только на сайте ФСВНГ." }, { status: 403, headers: cors(origin) });

    let q = "";
    try {
      const body = await request.json();
      q = String(body.q || "").slice(0, MAX_Q).trim();
    } catch (e) {}
    if (!q)
      return Response.json({ error: "Пустой вопрос" }, { status: 400, headers: cors(origin) });

    const found = pick(q);
    if (!found.length)
      return Response.json(
        { answer: "По этому вопросу в уставах ничего не нашлось. Переформулируй или уточни у старшего состава.", refs: [] },
        { headers: cors(origin) }
      );

    const context = found
      .map((c, i) => `[${i + 1}] ${c.d} — ${c.t}${c.r ? ` (источник: ${c.r})` : ""}\n${c.x}`)
      .join("\n\n");

    let answer = "";
    try {
      answer = await think(env, MODEL, q, context);
    } catch (e) {
      // основная модель может быть занята или выбран дневной лимит — пробуем лёгкую
      try {
        answer = await think(env, FALLBACK, q, context);
      } catch (e2) {
        const m = String(e2.message || e2);
        return Response.json(
          { error: /limit|capacity|429/i.test(m) ? "Помощник перегружен, попробуй через минуту." : "Помощник временно недоступен.", detail: m.slice(0, 200) },
          { status: 502, headers: cors(origin) }
        );
      }
    }

    if (!answer) answer = "Пустой ответ, переформулируй вопрос.";
    const refs = [...new Set(found.map((c) => c.r).filter(Boolean))];

    return Response.json({ answer, refs }, { headers: cors(origin) });
  },
};

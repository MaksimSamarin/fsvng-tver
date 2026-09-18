// Помощник по уставам ФСВНГ — Cloudflare Worker + Workers AI
// Модель крутится внутри Cloudflare: внешний Groq режет запросы с адресов воркеров (403 Forbidden).
import { KB } from "./kb.js";

const MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
const FALLBACK = "@cf/meta/llama-3.1-8b-instruct";
const TOP_K = 8;          // сколько фрагментов подкладываем в запрос
const MAX_Q = 600;        // ограничение длины вопроса
const MAX_HIST = 3;       // сколько прошлых пар вопрос-ответ помним
const MIN_SCORE = 8;      // ниже этого считаем, что вопрос не про наши документы

const SYSTEM = `Ты — инструктор Кадровой службы ФСВНГ (Росгвардия) на RP-сервере «Тверской» в GTA 5 RP.
Отвечаешь курсантам, которые описывают игровую ситуацию и спрашивают, как действовать.

ПРАВИЛА ОТВЕТА:
1. Отвечай ТОЛЬКО на основании фрагментов, которые даны в запросе. Ничего не выдумывай и не добавляй от себя.
2. Если во фрагментах нет ответа — ответь ОДНОЙ строкой: «В документах этого нет, уточни у старшего состава».
   В этом случае НЕ пиши список действий и НЕ пиши строку «Основание».
3. Формат ответа: короткий вывод одной строкой, затем от 2 до 5 пунктов порядка действий. Больше пяти пунктов не давай.
4. В конце строка «Основание:» — только те статьи, которые действительно есть среди поданных фрагментов,
   в том же виде, что в поле «источник»: «УКПС ст. 36, ДУ ст. 10». Никогда не пиши номера фрагментов из квадратных скобок.
5. Пиши по-русски, коротко и по-военному чётко. Без вступлений вроде «конечно» и «давайте разберём».
6. Если в ситуации есть риск нарушения — отдельной строкой предупреди, что за это грозит.
7. Команды в игре приводи точно: /f — рация IC, /fb — OOC, /me и /do — отыгровка.
8. Уголовный кодекс и КоАП — это статьи для нарушителя, а уставы — правила для самого курсанта. Не путай их местами.`;

// вопрос «что грозит за это» требует не инструкции, а статьи с санкцией
const PENALTY_MODE = `

СЕЙЧАС курсант спрашивает, что грозит за деяние. Отвечай иначе: НЕ давай порядок действий и НЕ нумеруй шаги.
Назови статью с её названием, приоритет розыска (звёздочки из фрагмента, если есть) и наказание — две-три строки.
Если в статье несколько частей с разными наказаниями — перечисли их коротко, каждую со своим наказанием.`;

// --- грубая нормализация русского слова: отбрасываем окончание ---
function stem(w) {
  w = w.toLowerCase().replace(/ё/g, "е");
  return w.length > 5 ? w.slice(0, w.length - 2) : w;
}
function tokens(s) {
  return (s.toLowerCase().replace(/ё/g, "е").match(/[а-яa-z0-9]{3,}/gi) || []).map(stem);
}

// Слова-связки смысла не несут, но легко набирают вес на длинном вопросе
const STOP = new Set(
  ("что это как где когда почему зачем можно нужно надо мне меня мой если его она они для при или "
   + "тоже еще уже так там тут вот быть есть делать сделать будет может этот который все него нее них "
   + "тебя себя свой этого этом этих был была было были очень просто вообще именно потом после этим "
   + "теперь тогда значит пока чтобы скажи подскажи расскажи вопрос ситуация случай").split(" ").map(stem)
);

// Курсант пишет по-человечески, кодекс — по-канцелярски. Мостик между ними.
const SYN = {
  "мат": "оскорбление неприличной форме честь достоинство",
  "матер": "оскорбление неприличной форме",
  "лексик": "оскорбление неприличной форме",
  "ненормативн": "оскорбление неприличной форме",
  "обозв": "оскорбление унижение чести",
  "оскорб": "оскорбление унижение чести достоинства",
  "хамит": "оскорбление неповиновение",
  "угон": "неправомерное завладение транспортным средством",
  "угна": "неправомерное завладение транспортным средством",
  "укра": "кража тайное хищение чужого имущества",
  "воров": "кража хищение",
  "ограб": "грабеж разбой открытое хищение",
  "изби": "побои насилие вред здоровью",
  "удар": "побои насилие вред здоровью",
  "убил": "убийство причинение смерти",
  "стрел": "оружие применение огнестрельного",
  "ствол": "оружие огнестрельное",
  "пьян": "состоянии опьянения алкогольного",
  "нарко": "наркотических средств психотропных веществ",
  "взятк": "взятки получение дача подкуп",
  "докум": "документы удостоверение личности предъявить",
  "пропуск": "пропускной режим пропуск допуск территорию",
  "сбежа": "побег уклонение скрылся",
  "убежа": "побег уклонение скрылся",
  "напад": "нападение посягательство насилие применение",
  "угроз": "угроза убийством причинением вреда",
  "поддел": "подделка подложных документов",
  "мошен": "мошенничество обман злоупотребление доверием",
  "прогул": "уклонение самовольное оставление неявка",
  "самовол": "самовольное оставление части места службы",
  "опозда": "неявка срок уклонение построение",
  "дезерт": "дезертирство самовольное оставление",
  "приказ": "неисполнение приказа начальника",
  "маск": "маска лицо скрыто",
  "задерж": "задержание доставление ограничение свободы",
  "досмотр": "досмотр личный вещей транспортного средства",
};

// «что грозит за угон» и «что делать на посту» — разные вопросы и разные документы
const ASK_PENALTY = /(что (?:ему |ей |им |мне )?(?:будет|грозит|светит)|како[ей] наказани|наказание за|како[йгв] срок|срок за|штраф|сколько дадут|кака[яю] стать|стать[яю] за|что за это|ответственност|посад|сколько лет|сколько месяц|како[ей] нарушени|нарушение за|что нарушил|чем грозит)/i;
const ASK_HOWTO = /(что делать|что мне делать|как действовать|как быть|как поступить|порядок действ|могу ли|можно ли|имею ли|вправе ли|обязан ли|как оформить|как доложить|как задержать|как проверить)/i;

// какой документ курсант назвал сам
const HINTS = [
  ["укпс", "УКПС"], ["караульн", "УКПС"], ["постов", "УКПС"],
  ["дисциплинарн", "ДУ"], [" ду ", "ДУ"],
  ["уголовн", "УК"], [" ук ", "УК"], ["ук ро", "УК"],
  ["коап", "КоАП"], ["админист", "КоАП"],
  ["устав вс", "ВУ"], [" ву ", "ВУ"],
];
function docHint(q) {
  const low = " " + q.toLowerCase().replace(/ё/g, "е") + " ";
  for (const [needle, abbr] of HINTS) if (low.includes(needle)) return abbr;
  return null;
}

const INDEX = KB.map((c) => ({
  c,
  toks: new Set(tokens(c.t + " " + c.x)),
  head: new Set(tokens(c.t)),
}));

// редкое слово весит больше частого
const DF = new Map();
for (const { toks } of INDEX) for (const t of toks) DF.set(t, (DF.get(t) || 0) + 1);
const NDOC = INDEX.length;
function idf(t) {
  const df = DF.get(t) || 0;
  return df ? Math.log(1 + NDOC / df) : 0;
}

function pick(question, prev) {
  // уточняющий вопрос вроде «а после задержания?» сам по себе бессмыслен — добавляем прошлый
  const full = prev ? prev + " " + question : question;
  const base = tokens(full);
  const extra = [];
  const low = full.toLowerCase().replace(/ё/g, "е");
  for (const key in SYN) if (low.includes(key)) extra.push(...tokens(SYN[key]));

  const num = question.match(/\b\d+(?:\.\d+)?\b/g) || [];
  const hint = docHint(question);
  const penalty = ASK_PENALTY.test(question);
  const howto = ASK_HOWTO.test(question) && !penalty;

  const scored = INDEX.map(({ c, toks, head }) => {
    let s = 0;
    for (const t of new Set(base)) if (toks.has(t) && !STOP.has(t)) s += idf(t) * (head.has(t) ? 2.2 : 1);
    for (const t of new Set(extra)) if (toks.has(t) && !STOP.has(t)) s += idf(t) * 0.7 * (head.has(t) ? 2.2 : 1);
    const mine = hint && c.r && c.r.indexOf(hint + " ") === 0;
    if (hint && mine) s += 3;
    for (const n of num) {
      if (!c.r || !c.r.includes(" " + n)) continue;
      // «статья 37 УКПС» — номер должен сыграть только для названного документа
      if (!hint) s += 12;
      else if (mine) s += 20;
    }
    // спрашивают про наказание — вперёд кодексы; спрашивают про порядок службы — уставы
    const isCode = !!c.r && (c.r.indexOf("УК ") === 0 || c.r.indexOf("КоАП ") === 0);
    if (penalty && isCode) s *= 1.4;
    if (howto && !isCode) s *= 1.3;
    return { c, s };
  })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s);

  if (!scored.length || scored[0].s < MIN_SCORE) return [];
  const out = scored.slice(0, TOP_K).map((x) => x.c);
  out.penalty = penalty;      // наверху по этому флагу выбирается формат ответа
  return out;
}

// --- вычищаем из «Основание:» статьи, которых модели не давали ---
const REF_RE = /(УКПС|КоАП|ДУ|ВУ|УК)\s*(?:ст\.?\s*)?(\d+(?:\.\d+)*)|ст\.?\s*(\d+(?:\.\d+)*)\s*(УКПС|КоАП|ДУ|ВУ|УК)/gi;

function fixRefs(answer, allowed) {
  const ok = new Set(allowed);
  return answer.replace(/^\s*Основание:.*$/gim, (line) => {
    const keep = [];
    let m;
    REF_RE.lastIndex = 0;
    while ((m = REF_RE.exec(line))) {
      const abbr = (m[1] || m[4] || "").toUpperCase().replace("КОАП", "КоАП");
      const num = m[2] || m[3];
      const ref = abbr + " ст. " + num;
      if (ok.has(ref) && !keep.includes(ref)) keep.push(ref);
    }
    return keep.length ? "Основание: " + keep.join(", ") : "";
  }).trim();
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

async function think(env, model, messages) {
  const out = await env.AI.run(model, { temperature: 0.2, max_tokens: 700, messages });
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
    let hist = [];
    try {
      const body = await request.json();
      q = String(body.q || "").slice(0, MAX_Q).trim();
      if (Array.isArray(body.h))
        hist = body.h.slice(-MAX_HIST).map((p) => ({
          q: String(p.q || "").slice(0, MAX_Q),
          a: String(p.a || "").slice(0, 500),
        })).filter((p) => p.q && p.a);
    } catch (e) {}
    if (!q)
      return Response.json({ error: "Пустой вопрос" }, { status: 400, headers: cors(origin) });

    const prevQ = hist.length ? hist[hist.length - 1].q : "";
    const found = pick(q, prevQ);
    if (!found.length)
      return Response.json(
        { answer: "В документах этого нет. Переформулируй вопрос или уточни у старшего состава.", refs: [] },
        { headers: cors(origin) }
      );

    const context = found
      .map((c, i) => `[${i + 1}] ${c.d} — ${c.t}${c.r ? ` (источник: ${c.r})` : ""}\n${c.x}`)
      .join("\n\n");

    const messages = [{ role: "system", content: SYSTEM + (found.penalty ? PENALTY_MODE : "") }];
    for (const p of hist) {
      messages.push({ role: "user", content: p.q });
      messages.push({ role: "assistant", content: p.a });
    }
    messages.push({
      role: "user",
      content: `ФРАГМЕНТЫ ДОКУМЕНТОВ:\n\n${context}\n\n---\nСИТУАЦИЯ КУРСАНТА: ${q}`,
    });

    let answer = "";
    try {
      answer = await think(env, MODEL, messages);
    } catch (e) {
      // основная модель может быть занята или выбран дневной лимит — пробуем лёгкую
      try {
        answer = await think(env, FALLBACK, messages);
      } catch (e2) {
        const m = String(e2.message || e2);
        return Response.json(
          { error: /limit|capacity|429/i.test(m) ? "Помощник перегружен, попробуй через минуту." : "Помощник временно недоступен.", detail: m.slice(0, 260) },
          { status: 502, headers: cors(origin) }
        );
      }
    }

    const refs = [...new Set(found.map((c) => c.r).filter(Boolean))];
    answer = fixRefs(answer || "Пустой ответ, переформулируй вопрос.", refs);

    return Response.json({ answer, refs }, { headers: cors(origin) });
  },
};

// открыто для локальных тестов (сайт/помощник/test.mjs), на работу воркера не влияет
export { pick, fixRefs, docHint };

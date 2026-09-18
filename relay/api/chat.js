// Реле для OpenRouter. Стоит вне Cloudflare: подзапрос воркера тащит за собой страну посетителя,
// а OpenRouter гео-блокирует Россию. Отсюда запрос уходит с американского адреса без чужих меток.
//
// Вход:  POST { messages: [...], max_tokens?: 550, model?: "vendor/slug:free" }  + заголовок X-Relay-Key
// Выход: { answer, model }  либо  { error, detail }

// Бесплатные модели OpenRouter в порядке предпочтения. Точные id берутся из каталога при первом вызове,
// чтобы не зависеть от переименований — здесь только образцы имён.
const PRIORITY = [
  /deepseek.*v4.*flash/i,
  /nemotron-3-super/i,
  /inkling-small/i,
  /ling-3.*flash/i,
  /qwen3\.8-27b/i,
  /gemma-4-26b/i,
  /glm-5/i,
];

let cache = { at: 0, ids: [] };

async function freeModels(key) {
  if (cache.ids.length && Date.now() - cache.at < 6 * 3600e3) return cache.ids;
  const r = await fetch("https://openrouter.ai/api/v1/models", { headers: { Authorization: `Bearer ${key}` } });
  if (!r.ok) throw new Error("каталог моделей: HTTP " + r.status);
  const d = await r.json();
  const free = (d.data || []).map((m) => m.id).filter((id) => id.endsWith(":free"));
  const ids = [];
  for (const re of PRIORITY) {
    const hit = free.find((id) => re.test(id));
    if (hit) ids.push(hit);
  }
  cache = { at: Date.now(), ids };
  return ids;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  if (!process.env.RELAY_SECRET || req.headers["x-relay-key"] !== process.env.RELAY_SECRET)
    return res.status(403).json({ error: "forbidden" });
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) return res.status(500).json({ error: "OPENROUTER_API_KEY не задан" });

  const body = req.body || {};
  const messages = Array.isArray(body.messages) ? body.messages : null;
  if (!messages) return res.status(400).json({ error: "нужно поле messages" });

  let ids;
  try {
    ids = await freeModels(key);
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e) });
  }
  if (body.model) ids = [body.model, ...ids.filter((id) => id !== body.model)];
  if (!ids.length) return res.status(502).json({ error: "в каталоге не нашлось ни одной бесплатной модели из списка" });

  const errors = [];
  for (const model of ids) {
    try {
      const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
          "HTTP-Referer": "https://maksimsamarin.github.io/fsvng-tver/",
          "X-Title": "FSVNG assistant",
        },
        body: JSON.stringify({ model, messages, temperature: 0.2, max_tokens: body.max_tokens || 550 }),
      });
      const txt = await r.text();
      if (!r.ok) { errors.push(`${model}: HTTP ${r.status} ${txt.slice(0, 120)}`); continue; }
      const d = JSON.parse(txt);
      const answer = (d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content || "").trim();
      if (!answer) { errors.push(`${model}: пустой ответ`); continue; }
      return res.status(200).json({ answer, model });
    } catch (e) {
      errors.push(`${model}: ${String(e.message || e).slice(0, 120)}`);
    }
  }
  return res.status(502).json({ error: "ни одна модель не ответила", detail: errors.slice(0, 6) });
};

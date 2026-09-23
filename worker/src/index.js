// Verdict store for the bag tracker. Two routes, one KV namespace, one shared token.
//   POST /v  {token, kind: "listing"|"bag", key, value}   -> 204 (value "clear" deletes)
//   GET  /v  (Authorization: Bearer <token>)              -> {listings: {key: {v, t}}, bags: {id: {status, t}}}
const VALUES = {
  listing: new Set(["no", "keep", "clear"]),
  bag: new Set(["wanted", "found", "owned", "clear"]),
};
const KEY_RE = {
  listing: /^(ebay|poshmark|depop|mercari):[A-Za-z0-9_.|-]{1,120}$/,  // eBay Browse ids look like v1|254582474636|0
  bag: /^[a-z0-9-]{1,40}$/,                                           // bag ids from config.yaml
};
const TTL_SECONDS = 60 * 24 * 3600;

function cors(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
const empty = (status, env) => new Response(null, { status, headers: cors(env) });
const json = (obj, status, env) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...cors(env) } });

async function listAll(env) {
  const out = { listings: {}, bags: {} };
  let cursor;
  do {
    const page = await env.VERDICTS.list({ cursor });
    for (const { name } of page.keys) {
      const raw = await env.VERDICTS.get(name);
      if (!raw) continue;
      let rec;
      try { rec = JSON.parse(raw); } catch { continue; }
      if (name.startsWith("l:")) out.listings[name.slice(2)] = rec;
      else if (name.startsWith("b:")) out.bags[name.slice(2)] = rec;
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return empty(204, env);
    if (url.pathname !== "/v") return empty(404, env);

    if (request.method === "GET") {
      const auth = request.headers.get("Authorization") || "";
      const presented = auth.startsWith("Bearer ") ? auth.slice(7) : null;
      if (!env.TOKEN || presented !== env.TOKEN) return empty(401, env);
      return json(await listAll(env), 200, env);
    }

    if (request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return empty(400, env); }
      if (!body || !env.TOKEN || body.token !== env.TOKEN) return empty(401, env);
      const { kind, key, value } = body;
      if (!Object.prototype.hasOwnProperty.call(VALUES, kind) || typeof key !== "string" ||
          !KEY_RE[kind].test(key) || !VALUES[kind].has(value)) {
        return empty(400, env);
      }
      const k = (kind === "listing" ? "l:" : "b:") + key;
      if (value === "clear") {
        await env.VERDICTS.delete(k);
        return empty(204, env);
      }
      const t = new Date().toISOString();
      const rec = kind === "listing" ? { v: value, t } : { status: value, t };
      await env.VERDICTS.put(k, JSON.stringify(rec), { expirationTtl: TTL_SECONDS });
      return empty(204, env);
    }

    return empty(405, env);
  },
};

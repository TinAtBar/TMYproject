// Hash-Router: #/route/param?query
const routes = [];
let current = null;
let handler = null;
export function route(pattern, view) {
  const keys = []; const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '$');
  routes.push({ re, keys, view, pattern });
}
export function parseHash() {
  const raw = location.hash.slice(1) || '/start';
  const [path, q] = raw.split('?');
  const query = Object.fromEntries(new URLSearchParams(q || ''));
  return { path, query };
}
export function resolve() {
  const { path, query } = parseHash();
  for (const r of routes) {
    const m = r.re.exec(path);
    if (m) { const params = {}; r.keys.forEach((k, i) => params[k] = decodeURIComponent(m[i + 1])); return { ...r, params, query, path }; }
  }
  return null;
}
export function go(path, replace = false) {
  const url = '#' + path;
  if (replace) history.replaceState(null, '', url); else if (location.hash !== url) history.pushState(null, '', url);
  dispatch();
}
// Query ändern ohne Neuaufbau
export function setQuery(query, replace = true) {
  const { path } = parseHash();
  const p = new URLSearchParams(); for (const [k, v] of Object.entries(query)) if (v !== '' && v != null && v !== false) p.set(k, v);
  const s = p.toString(); const url = '#' + path + (s ? '?' + s : '');
  if (replace) history.replaceState(null, '', url); else history.pushState(null, '', url);
}
export function onRoute(fn) { handler = fn; }
export function dispatch() { current = resolve(); handler && handler(current); }
export function currentRoute() { return current; }
window.addEventListener('popstate', dispatch);
window.addEventListener('hashchange', () => { const r = resolve(); if (!current || !r || r.path !== current.path || JSON.stringify(r.query) !== JSON.stringify(current.query)) dispatch(); });

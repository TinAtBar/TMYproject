// R29-C (Punkt 122): Projektleiste als Galerie – gemeinsam für OPL (Filter) und Fertigungsbesprechung (Auswahl).
// Weiches Einrasten (scroll-snap), aktives Projekt mittig + leicht vergrößert, Pfeile, Tastatur ←/→, Wischen,
// Randverlauf statt Scrollbalken. Respektiert „Animationen aus“ (html[data-anim=aus]) und prefers-reduced-motion.
// Nutzertext nur über h()/textContent.
import { h, icon, clear } from './util.js';

const ruhig = () => (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) ||
  document.documentElement.dataset.anim === 'aus';

/** Kachel-Daten aus einer Projektzeile von /api/fertigung(/kacheln). */
export function projektKachel(p) {
  return {
    id: String(p.id), nr: p.ist_allgemein ? 'Allgemein' : String(p.nummer || '').replace(/-00$/, ''),
    sub: p.ist_allgemein ? 'Firma' : (p.kunde_kurz || ''), allg: !!p.ist_allgemein,
    offen: p.offen || 0, ueberfaellig: p.ueberfaellig || 0, geaendert: p.geaendert || 0,
    title: `${p.ist_allgemein ? 'Allgemein' : p.nummer} ${p.bezeichnung || ''}\n${p.offen || 0} offen · ${p.ueberfaellig || 0} überfällig · ${p.geaendert || 0} geändert`,
  };
}

/**
 * opts: { label, auswahl (true = genau ein aktives Projekt, Pfeile/Tasten wechseln das Projekt),
 *         onWaehle(id, event), vorne: [Element], hinten: [Element] }
 * → { el, setze(kacheln, aktivIds:Set|Array), zentriere() }
 */
export function projektGalerie(opts = {}) {
  let kacheln = [], aktiv = new Set();
  const track = h('div', { class: 'pg-track', role: 'toolbar', 'aria-label': opts.label || 'Projekte' });
  const pfeil = (r) => h('button', {
    class: 'pg-pfeil pg-' + r, type: 'button', 'aria-label': r === 'l' ? 'Vorheriges Projekt' : 'Nächstes Projekt',
    title: r === 'l' ? 'Zurück (←)' : 'Weiter (→)', onclick: () => schritt(r === 'l' ? -1 : 1, true),
  }, icon(r === 'l' ? 'chevL' : 'chevR', 18));
  const links = pfeil('l'), rechts = pfeil('r');
  const el = h('div', { class: 'pg' + (opts.auswahl ? ' pg-auswahl' : '') }, links, h('div', { class: 'pg-rahmen' }, track), rechts);

  function kachelEl(k) {
    const an = k.id === '' ? aktiv.size === 0 : aktiv.has(k.id);
    return h('button', {
      type: 'button', class: 'fb-tile pg-tile' + (an ? ' on' : '') + (k.allg ? ' allg' : ''), 'aria-pressed': String(an),
      'aria-current': opts.auswahl && an ? 'true' : null, dataset: { id: k.id }, title: k.title || '',
      onclick: e => opts.onWaehle && opts.onWaehle(k.id, e),
    }, h('span', { class: 'fb-tile-nr' }, k.nr), k.sub != null ? h('span', { class: 'fb-tile-sub pg-kunde' }, k.sub) : null,
      k.id !== '' ? h('span', { class: 'fb-tile-z' },
        h('span', { class: 'fb-n', title: 'offen' }, String(k.offen)),
        k.ueberfaellig ? h('span', { class: 'fb-od', title: 'überfällig' }, '!', String(k.ueberfaellig)) : null,
        k.geaendert ? h('span', { class: 'fb-ch', title: 'geändert' }, icon('edit', 12), String(k.geaendert)) : null) : null);
  }
  function tiles() { return [...track.querySelectorAll('.pg-tile')]; }
  function rand() {
    const max = track.scrollWidth - track.clientWidth - 2;
    el.classList.toggle('pg-mehr-l', track.scrollLeft > 2);
    el.classList.toggle('pg-mehr-r', track.scrollLeft < max);
    if (opts.auswahl) {
      const ts = tiles(), i = ts.findIndex(t => t.classList.contains('on'));
      links.disabled = i <= 0; rechts.disabled = i < 0 || i >= ts.length - 1;
    } else { links.disabled = track.scrollLeft <= 2; rechts.disabled = track.scrollLeft >= max; }
  }
  function zentriere(sofort) {
    const t = track.querySelector('.pg-tile.on[data-id]:not([data-id=""])') || (opts.auswahl ? null : null);
    if (!t) { rand(); return; }
    const ziel = t.offsetLeft - (track.clientWidth - t.offsetWidth) / 2;
    try { track.scrollTo({ left: Math.max(0, ziel), behavior: sofort || ruhig() ? 'auto' : 'smooth' }); } catch { track.scrollLeft = Math.max(0, ziel); }
    setTimeout(rand, ruhig() ? 0 : 350);
  }
  function schritt(d, perKnopf) {
    if (opts.auswahl) {
      const ts = tiles(), i = ts.findIndex(t => t.classList.contains('on'));
      const n = ts[Math.max(0, Math.min(ts.length - 1, (i < 0 ? 0 : i) + d))];
      if (n && n.dataset.id !== (ts[i] && ts[i].dataset.id)) { opts.onWaehle && opts.onWaehle(n.dataset.id, {}); }
      return;
    }
    if (perKnopf) {
      const w = track.clientWidth * 0.8 * d;
      try { track.scrollBy({ left: w, behavior: ruhig() ? 'auto' : 'smooth' }); } catch { track.scrollLeft += w; }
      return;
    }
    const ts = [...track.querySelectorAll('.fb-tile')], i = ts.indexOf(document.activeElement);
    const n = ts[i + d]; if (n) { n.focus(); n.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: ruhig() ? 'auto' : 'smooth' }); }
  }
  track.addEventListener('keydown', e => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault(); schritt(e.key === 'ArrowRight' ? 1 : -1, false);
    if (opts.auswahl) setTimeout(() => { const t = track.querySelector('.pg-tile.on'); t && t.focus({ preventScroll: true }); }, 0);
  });
  track.addEventListener('scroll', () => rand(), { passive: true });
  // Mausrad senkrecht → waagerecht (Desktop ohne Touchpad)
  track.addEventListener('wheel', e => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && track.scrollWidth > track.clientWidth) { track.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => rand()).observe(track);

  function setze(neu, ids) {
    if (neu) kacheln = neu;
    if (ids) aktiv = new Set([...ids].map(String));
    const fokus = document.activeElement && track.contains(document.activeElement) ? document.activeElement.dataset.id : null;
    clear(track).append(...(opts.vorne || []), ...kacheln.map(kachelEl), ...(opts.hinten || []));
    if (fokus != null) { const b = track.querySelector(`.fb-tile[data-id="${CSS.escape(fokus)}"]`); b && b.focus({ preventScroll: true }); }
    requestAnimationFrame(() => zentriere(!el.dataset.pgFertig)); el.dataset.pgFertig = '1';
  }
  return { el, setze, zentriere };
}

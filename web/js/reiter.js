// R29-G (127): Projekt-Reiter als Karteireiter mit Symbol vor dem Text.
// Alle Reiter stehen direkt in der Zeile, solange Platz ist; was nicht passt, wandert automatisch ins „Mehr“-Menü
// (ResizeObserver, Fensterbreite/Handy). Der aktive Reiter bleibt immer sichtbar. Handy: nur Symbole (CSS design29.css).
import { h, icon } from './util.js';
import { menu } from './ui.js';

/** Symbol je Reiter-Schlüssel (Reiter anderer Pakete können `icon` in registerProjektTab mitgeben). */
export const REITER_ICON = {
  uebersicht: 'grid', opl: 'list', termine: 'cal', budget: 'clock', dokumente: 'doc', baugruppen: 'boxes',
  nachtraege: 'docPlus', verlauf: 'history', qip: 'antrag', kickoff: 'flag', fortschritt: 'okc', angebote: 'angebot',
  gantt: 'rows', fertigung: 'fertigung', ablage: 'folder', freigaben: 'seal', export: 'excel', exporte: 'excel',
};

/**
 * Reine Verteil-Logik (ohne DOM, testbar):
 * breiten = Breite je Reiter (px, inkl. Abstand), platz = verfügbare Breite, mehrBreite = Breite des „Mehr“-Knopfs,
 * aktiv = Index des aktiven Reiters (-1 = keiner). Reihenfolge bleibt; ab dem ersten Reiter, der nicht passt,
 * wandert alles Weitere ins Menü – außer dem aktiven Reiter, der immer sichtbar bleibt.
 * → { sichtbar: [Indizes], mehr: [Indizes] }
 */
export function verteile(breiten, platz, mehrBreite, aktiv = -1) {
  const n = breiten.length;
  const summe = breiten.reduce((a, b) => a + b, 0);
  if (summe <= platz) return { sichtbar: [...Array(n).keys()], mehr: [] };
  const verf = platz - mehrBreite;
  let belegt = aktiv >= 0 && aktiv < n ? breiten[aktiv] : 0;
  const sichtbar = [], mehr = [];
  let voll = false;
  for (let i = 0; i < n; i++) {
    if (i === aktiv) { sichtbar.push(i); continue; }
    if (!voll && belegt + breiten[i] <= verf) { belegt += breiten[i]; sichtbar.push(i); }
    else { voll = true; mehr.push(i); }
  }
  return { sichtbar, mehr };
}

/**
 * Reiterleiste bauen. items: [[key, label, count, iconName?], …]; onchange(key).
 * Gibt das Element (.tabs.ph-tabs.reiter29) zurück; Verteilung läuft nach dem Einhängen automatisch.
 */
export function reiterLeiste(items, active, onchange, { mehrLabel = 'Mehr' } = {}) {
  const bar = h('div', { class: 'tabs ph-tabs reiter29', role: 'tablist' });
  const knoepfe = items.map(([k, l, count, ic]) => h('button', {
    role: 'tab', type: 'button', class: 'tab', 'aria-selected': String(k === active), title: l, dataset: { k }, onclick: () => onchange(k),
  }, icon(ic || REITER_ICON[k] || 'dot', 18), h('span', { class: 'tab-lbl' }, l), count != null ? h('span', { class: 'tab-count' }, count) : null));
  let mehrIdx = [];
  const mehr = h('button', {
    role: 'tab', type: 'button', class: 'tab ph-mehr-tab', 'aria-selected': 'false', 'aria-haspopup': 'menu', title: mehrLabel, hidden: true,
    onclick: e => menu(e.currentTarget, mehrIdx.map(i => {
      const [k, l, c, ic] = items[i];
      return { label: c != null ? `${l} (${c})` : l, icon: ic || REITER_ICON[k] || 'dot', fn: () => onchange(k) };
    })),
  }, icon('more', 18), h('span', { class: 'tab-lbl' }, mehrLabel), icon('chevD', 14));
  bar.append(...knoepfe, mehr);

  const aktivIdx = items.findIndex(x => x[0] === active);
  let breiten = null;
  function verteilen() {
    if (!bar.isConnected) return;
    const platz = bar.clientWidth;
    if (!platz) return;
    // Breiten einmal je Layout-Modus messen (alle sichtbar)
    knoepfe.forEach(b => { b.hidden = false; }); mehr.hidden = false;
    const gap = parseFloat(getComputedStyle(bar).columnGap) || 0;
    breiten = knoepfe.map(b => b.getBoundingClientRect().width + gap);
    const mb = mehr.getBoundingClientRect().width + gap;
    const v = verteile(breiten, platz - 2, mb, aktivIdx);
    mehrIdx = v.mehr;
    knoepfe.forEach((b, i) => { b.hidden = v.mehr.includes(i); });
    mehr.hidden = !v.mehr.length;
  }
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => { if (!bar.isConnected) { ro.disconnect(); return; } requestAnimationFrame(verteilen); });
    ro.observe(bar);
  } else requestAnimationFrame(verteilen);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => requestAnimationFrame(verteilen)).catch(() => {});
  setTimeout(verteilen, 400); // Zähler/Schrift nachgeladen
  return bar;
}

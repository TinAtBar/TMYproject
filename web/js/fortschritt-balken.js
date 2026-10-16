// R26-C1: wiederverwendbarer Fortschritts-/Stundenbalken (z. B. für Dashboard-Kacheln)
// balken({ prozent, art: 'fortschritt' | 'stunden', farbe?, onclick?, titel? }) → HTMLElement
import { h } from './util.js';

export function balken({ prozent, art = 'fortschritt', farbe, onclick, titel } = {}) {
  const leer = prozent == null || prozent === '' || isNaN(+prozent);
  const p = leer ? 0 : Math.max(0, +prozent);
  const label = art === 'stunden' ? 'Stunden' : 'Fortschritt';
  const text = leer ? '–' : `${Math.round(p)} %`;
  const fill = h('span', { class: 'fb-fill', style: { width: `${Math.min(100, p)}%` } });
  if (farbe) fill.style.background = farbe;
  const track = h('span', {
    class: 'fb-track', role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': '100',
    'aria-valuenow': String(Math.round(Math.min(p, 100))), 'aria-label': `${label}: ${text}`,
  }, fill);
  const cls = `fb-balken fb-${art}` + (p > 100 ? ' fb-ueber' : '') + (leer ? ' fb-leer' : '') + (onclick ? ' fb-klick' : '');
  const kids = [h('span', { class: 'fb-name' }, label), track, h('span', { class: 'fb-wert' }, text)];
  return onclick
    ? h('button', { type: 'button', class: cls, title: titel || `${label}: ${text}`, onclick }, ...kids)
    : h('div', { class: cls, title: titel || `${label}: ${text}` }, ...kids);
}

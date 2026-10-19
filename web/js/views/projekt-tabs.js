// Registrierung zusätzlicher Reiter auf der Projektseite (Besitz: Agent B).
// registerProjektTab({ key, label, count?: (data) => number|null, render: (el, ctx) => void, order?, sichtbar?: (data) => bool })
// ctx: { data, projekt, canEdit, reload, id }
// R29-G (127): optional icon: 'name' (Symbol aus util.js) – sonst Vorgabe aus reiter.js REITER_ICON
import { darf } from '../rechte.js'; // R26-E: Reiter mit { bereich } nur bei Recht
const reg = new Map();

export function registerProjektTab(def) {
  if (!def || !def.key || !def.label || typeof def.render !== 'function') throw new Error('registerProjektTab: key, label und render sind nötig');
  reg.set(def.key, { order: 100, ...def });
}

export function getProjektTabs(data) { // R26-C2: optional sichtbar(data) → Reiter ausblenden
  return [...reg.values()].filter(t => !t.bereich || darf(t.bereich)).filter(t => !data || typeof t.sichtbar !== 'function' || t.sichtbar(data)).sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
}

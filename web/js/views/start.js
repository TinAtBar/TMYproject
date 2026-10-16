// Start / Dashboard
import { h, icon, clear, avatar, activityIcon, fmtRel, fristState, fristIcon, fmtDate, fmtDateShort, chip } from '../util.js';
import { get, post } from '../api.js';
import { store, isPmOrAdmin } from '../store.js';
import { pageHead, loading, errorBox, empty, toast, toastErr } from '../ui.js';
import { describeActivity } from './opl-detail.js';
import { projectTile } from './projekte.js';
import { getRecent, emptyIcon } from '../extras.js';
import { isoDate, parseDate, today } from '../util.js';
import { qs } from '../api.js';
import { SEM, semVar } from '../semantik.js'; // R5-D
import { kachelRaster } from '../projekt-kachel.js'; // R26-G
import { darf } from '../rechte.js'; // R26-G
const WT = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

export function mount(el) {
  let data = null;
  const body = h('div', null, loading());
  const hour = new Date().getHours();
  const gruss = hour < 11 ? 'Guten Morgen' : hour < 18 ? 'Hallo' : 'Guten Abend';
  el.append(pageHead(`${gruss}, ${store.user.name.split(' ')[0]}`, store.seit ? `Dein letzter Besuch: ${fmtRel(store.seit)}` : 'Willkommen bei Barlage PM.'), body);

  async function load(o = {}) {
    try {
      const von = today(), bis = new Date(von); bis.setDate(bis.getDate() + 6);
      const pmA = isPmOrAdmin();
      const [d, kal, kach, rs] = await Promise.all([get('/dashboard'), get('/kalender' + qs({ von: isoDate(von), bis: isoDate(bis) })).catch(() => []),
        get('/dashboard/kacheln').catch(() => null), pmA ? get('/reststunden/status').catch(() => null) : null]); // R26-G
      data = d; data._kal = kal || []; data._kacheln = kach; data._rest = rs; render();
    }
    catch (e) { if (!o.live) clear(body).append(errorBox(e, load)); }
  }
  function kpi(v, label, href, cls) { return h('a', { class: 'kpi ' + (cls || ''), href }, h('span', { class: 'v' }, v ?? 0), h('span', { class: 'l' }, label)); }
  function kchip(v, l, href, cls, ic) { return h('a', { class: 'kpi-chip' + (cls ? ' ' + cls : ''), href }, ic ? icon(ic, 15) : null, h('strong', null, v ?? 0), ' ', l); } // R4-P
  function sep() { return h('span', { class: 'kpi-sep', 'aria-hidden': 'true' }, '·'); } // R4-P
  function oplRow(it) {
    const fs = fristState(it.frist, false);
    return h('li', null, h('a', { href: '#/opl/' + it.id },
      h('span', { class: 'num muted small', style: { width: '40px' } }, '#' + (it.nr ?? it.id)),
      h('span', { class: 't' }, it.titel, h('div', { class: 'p mono' }, [it.baugruppe_nummer || it.projekt_nummer, it.sn].filter(Boolean).join(' · '))),
      it.frist ? h('span', { class: 'frist ' + fs.cls, style: { textAlign: 'right' } }, h('span', { class: 'd' }, fristIcon(fs.cls), fs.label), fs.sub ? h('span', { class: 'sub' }, fs.sub) : null) : h('span', { class: 'muted small' }, 'ohne Frist')));
  }
  function card(title, content, action) { return h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, title), action || null), content); }
  function list(items, rowFn, emptyText) {
    if (!items || !items.length) return h('div', { class: 'card-body muted' }, emptyText);
    return h('ul', { class: 'mini-list' }, items.slice(0, 12).map(rowFn));
  }
  function render() {
    const k = data.kennzahlen || {};
    const m = store.user.rolle === 'mitarbeiter' ? '&meine=1' : '';
    const seit = data.seit_letztem_besuch || [];
    const feed = !seit.length ? h('div', { class: 'card-body muted' }, 'Keine Änderungen seit deinem letzten Besuch.')
      : h('ul', { class: 'feed' }, seit.map(a => {
        const n = a.user_name || a.name || '–';
        const href = a.objekt === 'opl' || a.objekt === 'kommentar' || a.objekt === 'datei' ? (a.opl_id || a.objekt_id) && '#/opl/' + (a.opl_id || a.objekt_id) : a.objekt === 'angebot' ? '#/angebote/' + a.objekt_id : a.projekt_id ? '#/projekte/' + a.projekt_id : null;
        return h('li', null, h('span', { class: 'act-av' }, avatar(n), activityIcon(a)), h('div', { class: 'what' },
          h('div', null, h('strong', null, n), ' ', describeActivity(a)),
          a.titel ? (href ? h('a', { href }, a.titel) : h('span', null, a.titel)) : (href ? h('a', { href }, 'Öffnen') : null),
          h('div', { class: 'meta' }, [a.projekt_nummer, fmtRel(a.zeit)].filter(Boolean).join(' · '))));
      }));
    const gesehen = seit.length ? h('button', { class: 'btn btn-sm', onclick: async () => { try { await post('/dashboard/gesehen'); store.seit = new Date().toISOString(); toast('Alles als gesehen markiert.', 'ok'); load(); } catch (e) { toastErr(e); } } }, icon('check', 16), 'Alles als gesehen markieren') : null;

    const projekte = data.projekte || [];
    const woche = meineWoche();
    const recent = getRecent().slice(0, 6);
    const kach = data._kacheln; // R26-G: Kacheln + Heute (Sammelabruf)
    const kItems = kach ? kach.items : projekte;
    const blocks = [
      reststundenBanner(),
      kach && kach.heute ? heuteBlock(kach.heute) : null,
      h('div', { class: 'db-layout' },
        h('div', null,
          h('div', { class: 'db-sec' }, h('h2', null, store.user.rolle === 'controlling' || store.user.rolle === 'admin' ? 'Projekte' : 'Meine Projekte'), h('a', { class: 'btn btn-sm btn-ghost', href: '#/projekte' }, 'Alle Projekte')),
          kItems.length ? kachelRaster(kItems, { stundenSichtbar: !!(kach && kach.stunden_sichtbar), label: 'Projekt-Kacheln' }) : h('div', { class: 'card' }, empty('Keine Projekte', 'Sobald du einem Projekt zugeordnet bist, erscheint es hier.'))),
        h('aside', { class: 'db-kz', 'aria-label': 'Kennzahlen' }, card('Offene Punkte', h('div', { class: 'db-zahlen' },
          zahl(k.offen, 'offen', '#/opl?status_art=offen' + m), zahl(k.ueberfaellig, 'überfällig', '#/opl?status_art=offen&ueberfaellig=1' + m, k.ueberfaellig ? 'od' : ''),
          zahl(k.woche, 'diese Woche', '#/opl?status_art=offen&woche=1' + m), zahl(k.erledigt_7t, 'erledigt (7 T.)', '#/opl?status_art=abgeschlossen&sort=-geaendert_am'))),
          kach && kach.stunden_sichtbar ? ampelKennzahl(kach.items) : null)),
      h('div', { class: 'kpi-chips start-kpis', role: 'group', 'aria-label': 'Kennzahlen', hidden: true }, // R4-P (R26-G: ersetzt durch Kennzahlen rechts)
        kchip(k.offen, 'offen', '#/opl?status_art=offen' + m, 'info', 'circle'), sep(),
        kchip(k.ueberfaellig, 'überfällig', '#/opl?status_art=offen&ueberfaellig=1' + m, k.ueberfaellig ? 'danger' : '', 'alarm'), sep(),
        kchip(k.woche, 'diese Woche fällig', '#/opl?status_art=offen&woche=1' + m, k.woche ? 'warn' : '', 'clock'), sep(),
        kchip(k.erledigt_7t, 'erledigt (7 Tage)', '#/opl?status_art=abgeschlossen&sort=-geaendert_am', 'ok', 'okc')),
      h('div', { class: 'grid cols-2' }, woche,
        card('Zuletzt angesehen', recent.length ? h('ul', { class: 'mini-list' }, recent.map(r => h('li', null, h('a', { href: r.link }, h('span', { class: 't' }, r.titel, r.sub ? h('div', { class: 'p mono' }, r.sub) : null), h('span', { class: 'small muted' }, fmtRel(r.zeit)))))) : h('div', { class: 'card-body muted' }, 'Noch nichts angesehen – geöffnete Punkte, Projekte und Seriennummern erscheinen hier.'))),
      h('div', { class: 'grid cols-2', style: { marginTop: '16px' } },
        card(`Seit deinem letzten Besuch${seit.length ? ` (${seit.length})` : ''}`, feed, gesehen),
        h('div', { class: 'stack' },
          card('Meine Punkte', list(data.meine_opl, oplRow, 'Du bist gerade bei nichts als zuständig eingetragen.'), h('a', { class: 'btn btn-sm btn-ghost', href: '#/opl?status_art=offen&meine=1' }, 'Alle')),
          (data.wiedervorlagen || []).length ? card('Wiedervorlagen', list(data.wiedervorlagen, a => h('li', null, h('a', { href: '#/angebote/' + a.id }, h('span', { class: 't' }, a.bezeichnung || a.nummer, h('div', { class: 'p mono' }, a.nummer)), h('span', { class: fristState(a.wiedervorlage).cls === 'overdue' ? 'wv-due' : 'small' }, fmtDateShort(a.wiedervorlage)))), '')) : null)),
    ];
    if (isPmOrAdmin() && (data.team || data.ohne_verantwortlich || data.liegengeblieben)) {
      const team = data.team || [];
      const max = Math.max(1, ...team.map(t => t.offen || 0));
      blocks.push(h('h2', { style: { margin: '26px 0 12px' } }, 'Team & Steuerung'),
        h('div', { class: 'grid cols-2' },
          card('Offene Punkte je Person', !team.length ? h('div', { class: 'card-body muted' }, 'Keine Daten.') : h('ul', { class: 'mini-list' }, team.map(t => {
            const u = t.user || {}; const name = u.name || t.name || '–';
            return h('li', null, h('a', { href: `#/opl?status_art=offen&zustaendig_user_id=${u.id ?? t.user_id}` } /* R5-Z */, avatar(name), h('span', { class: 't' }, name, h('div', { class: 'hbar', style: { marginTop: '4px' } }, h('span', { style: { width: (100 * (t.offen || 0) / max) + '%' } }))),
              h('span', { class: 'num' }, h('strong', null, t.offen || 0), ' offen'), t.ueberfaellig ? h('span', { class: 'chip chip-danger' }, `${t.ueberfaellig} überfällig`) : null));
          }))),
          h('div', { class: 'stack' },
            card(`Niemand zuständig (${(data.ohne_verantwortlich || []).length})`, list(data.ohne_verantwortlich, oplRow, 'Bei allen Punkten ist jemand zuständig.')), // R5-Z
            card(`Ohne Frist (${(data.ohne_frist || []).length})`, list(data.ohne_frist, oplRow, 'Alle offenen Punkte haben eine Frist.')),
            card(`Liegengeblieben – 14 Tage ohne Änderung (${(data.liegengeblieben || []).length})`, list(data.liegengeblieben, oplRow, 'Nichts liegengeblieben.')))));
    }
    clear(body).append(...blocks);
  }
  // R26-G ---------------------------------------------------------------
  function zahl(v, l, href, cls) { return h('a', { class: 'db-zahl' + (cls ? ' ' + cls : ''), href }, h('b', null, v ?? 0), h('span', { class: 'small muted' }, l)); }
  function ampelKennzahl(items) {
    const n = a => items.filter(p => p.ampel === a).length;
    const rot = n('rot') + n('rot_voll'), bs = n('bernstein');
    return card('Stunden-Ampel', h('div', { class: 'db-zahlen' },
      h('div', { class: 'db-zahl' + (rot ? ' od' : '') }, h('b', null, rot), h('span', { class: 'small muted' }, 'Budget erreicht')),
      h('div', { class: 'db-zahl' }, h('b', null, bs), h('span', { class: 'small muted' }, 'über Fortschritt'))));
  }
  function reststundenBanner() {
    const rs = data._rest;
    if (!rs || !rs.hinweis) return null;
    const btn = h('button', { class: 'btn btn-sm', onclick: async () => {
      btn.disabled = true;
      try { const r2 = await post('/reststunden/abrufen'); toast(r2 && r2.meldung ? r2.meldung : 'Ist-Stunden werden aktualisiert.', 'ok'); load(); }
      catch (e) { toastErr(e); } finally { btn.disabled = false; } } }, icon('undo', 16), 'Aktualisieren');
    return h('div', { class: 'db-banner anim-einblenden', role: 'status' }, icon('alarm', 18), h('span', { class: 'sp' }, rs.hinweis_text || 'Ist-Stunden ggf. veraltet'), btn);
  }
  function heuteBlock(hb) {
    const li = (href, titel, sub, datum, od) => h('li', null, h('a', { href }, h('span', { class: 't' }, titel, sub ? h('div', { class: 'p mono' }, sub) : null),
      datum ? h('span', { class: 'frist' + (od ? ' overdue' : '') }, h('span', { class: 'd' }, od ? fristIcon('overdue') : null, fmtDateShort(datum))) : null));
    const heuteIso = isoDate(today());
    const fae = hb.faellig || [];
    const nUe = fae.filter(x => x.ueberfaellig).length, nHe = fae.length - nUe;
    const ms = (hb.meilensteine || []).map(x => li(darf('projekte_details') ? '#/projekte/' + x.projekt_id + '' : '#/opl?projekt_id=' + x.projekt_id, x.name || 'Meilenstein', x.projekt_nummer, x.datum, false));
    return h('section', { class: 'db-heute', 'aria-label': 'Heute' },
      card(`Heute für mich${fae.length ? ` (${nUe} überfällig · ${nHe} heute)` : ''}`, list(fae, x => li('#/opl/' + x.id, x.titel, x.projekt_nummer, x.frist, x.frist < heuteIso), 'Nichts überfällig oder heute fällig.')),
      card('Meilensteine – 14 Tage', ms.length ? h('ul', { class: 'mini-list' }, ms.slice(0, 12)) : h('div', { class: 'card-body muted' }, 'Keine Meilensteine in den nächsten 14 Tagen.')),
      card(`Neu / geändert${(hb.neu || []).length ? ` (${hb.neu.length})` : ''}`, list(hb.neu, x => li('#/opl/' + x.id, x.titel, x.projekt_nummer, x.frist, x.frist && x.frist < heuteIso), 'Keine neuen oder geänderten Punkte.')));
  }
  function meineWoche() {
    const me = store.user.id;
    const ueber = (data.meine_opl || []).filter(o => o.ueberfaellig);
    const ev = (data._kal || []).filter(e => (e.typ === 'opl' ? (e.zustaendig_user_ids || []).includes(me) && !e.erledigt /* R5-Z */ : !e.erledigt));
    const days = []; for (let i = 0; i < 7; i++) { const d = today(); d.setDate(d.getDate() + i); days.push(d); }
    const href = e => e.typ === 'opl' ? '#/opl/' + e.id : e.typ === 'wiedervorlage' ? '#/angebote/' + e.id : '#/projekte/' + e.projekt_id;
    const lbl = { opl: 'Punkt', meilenstein: 'Meilenstein', wiedervorlage: 'Wiedervorlage' };
    const TYP_SEM = { opl: 'offen', meilenstein: 'meilenstein', wiedervorlage: 'wiedervorlage' }; // R5-D
    const body2 = h('div', { class: 'week' },
      ueber.length ? h('div', { class: 'wk-day od' }, h('div', { class: 'wk-h' }, `Überfällig (${ueber.length})`), ueber.slice(0, 5).map(o => h('a', { class: 'wk-it', href: '#/opl/' + o.id }, h('span', { class: 'wk-t' }, o.titel), h('span', { class: 'small muted mono' }, o.baugruppe_nummer || o.projekt_nummer)))) : null,
      days.map(d => { const k = isoDate(d); const list = ev.filter(e => e.datum === k); if (!list.length) return null;
        return h('div', { class: 'wk-day' }, h('div', { class: 'wk-h' }, i18nDay(d)), list.map(e => h('a', { class: 'wk-it', href: href(e) }, h('span', { class: 'chip chip-outline chip-typ', style: { '--c': semVar(TYP_SEM[e.typ] || 'offen') } }, icon(SEM[TYP_SEM[e.typ] || 'offen'].icon, 13), lbl[e.typ]), h('span', { class: 'wk-t' }, e.titel), h('span', { class: 'small muted mono' }, e.projekt_nummer || '')))); }));
    if (!body2.children.length) body2.append(emptyIcon('cal', 'Ruhige Woche', 'In den nächsten 7 Tagen ist nichts für dich fällig.'));
    return card('Meine Woche', body2, h('a', { class: 'btn btn-sm btn-ghost', href: '#/kalender?ansicht=liste' }, 'Kalender'));
  }
  function i18nDay(d) { const n = Math.round((d - today()) / 864e5); return n === 0 ? 'Heute' : n === 1 ? 'Morgen' : `${WT[d.getDay()]}, ${fmtDate(isoDate(d))}`; }
  load();
  return { title: 'Start', refresh: load };
}

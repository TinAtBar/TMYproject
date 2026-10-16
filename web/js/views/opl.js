// Route /opl und /opl/:id
import { h, icon } from '../util.js';
import { setQuery, go } from '../router.js';
import { store } from '../store.js';
import { pageHead } from '../ui.js';
import { oplList } from './opl-list.js';
import { openOplPanel, newOplDialog, vorlageDialog } from './opl-detail.js';

export function mount(el, r) {
  let panel = null;
  const filters = Object.keys(r.query).length ? { ...r.query } : null; // R4-T: ohne URL-Filter → gespeicherte Filter des Benutzers
  const newBtn = h('button', { class: 'btn btn-primary', onclick: () => create() }, icon('plus', 18), 'Neuer Punkt');
  el.append(pageHead('Offene-Punkte-Liste', 'Alle Punkte über alle Projekte. Status direkt in der Liste ändern.', h('button', { class: 'btn', onclick: () => vorlageDialog({ ...store.context }, () => list.refresh()) }, icon('list', 18), 'Aus Vorlage'), newBtn));
  const host = h('div'); el.append(host);
  const list = oplList(host, {
    filters,
    onFilters: f => setQuery(f),
    onOpen: id => openDetail(id),
    onNew: () => create(),
  });
  function create() { newOplDialog({ ...store.context }, it => { list.refresh(); openDetail(it.id); }); }
  function openDetail(id) {
    if (panel && panel.id == id) return;
    if (panel) panel.close(true);
    const q = new URLSearchParams(location.hash.split('?')[1] || '').toString();
    history.replaceState(null, '', '#/opl/' + id + (q ? '?' + q : ''));
    list.setSelectedId(id);
    panel = openOplPanel(id, {
      onClose: () => { panel = null; const q2 = location.hash.split('?')[1]; history.replaceState(null, '', '#/opl' + (q2 ? '?' + q2 : '')); list.setSelectedId(null); },
      onChanged: () => list.refresh(),
      onNav: dir => { const items = list.items(); const i = items.findIndex(x => x.id == id); const n = items[i + dir]; if (n) openDetail(n.id); },
    });
  }
  if (r.params.id) openDetail(r.params.id);
  return {
    title: 'OPL', handlesN: true,
    refresh: o => { list.refresh(o); panel && panel.refresh(); },
    update: r2 => { if (r2.params.id) openDetail(r2.params.id); else if (panel) { panel.close(true); panel = null; } },
    destroy: () => { list.destroy(); panel && panel.close(true); },
  };
}

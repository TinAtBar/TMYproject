#!/usr/bin/env python3
"""Mini-Mock für die OPL-Oberfläche (nur Entwicklung, nur Standardbibliothek).
Start:  python3 web/dev/mock-server.py [port]   → http://localhost:8099  (Login: pm1 / opl2026)
Liefert web/ aus und gefälschte JSON-Antworten gemäß SPEC.md (Beispielprojekt).
"""
import json, os, sys, re, datetime as dt, random
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = dt.date.today()
D = lambda n: (T + dt.timedelta(days=n)).isoformat()
NOW = lambda: dt.datetime.now().isoformat(timespec='seconds')
rev = [1]

USERS = [dict(id=1, login='admin', name='Admin', rolle='admin', urlaub=0), dict(id=2, login='pm1', name='Projektleiter A', rolle='pm', urlaub=0),
         dict(id=3, login='pm2', name='Projektleiter B', rolle='pm', urlaub=0), dict(id=4, login='ma1', name='Mitarbeiter 1', rolle='mitarbeiter', urlaub=0),
         dict(id=5, login='ma2', name='Mitarbeiter 2', rolle='mitarbeiter', urlaub=0)]
SD = dict(
    status_opl=[dict(id=1, name='Offen', farbe='#d0d7e2', art='offen', pos=1, ist_start=1), dict(id=2, name='In Arbeit', farbe='#1f6feb', art='offen', pos=2),
                dict(id=3, name='Wartet', farbe='#f2b600', art='offen', pos=3), dict(id=4, name='Erledigt', farbe='#2b7a3d', art='abgeschlossen', pos=4),
                dict(id=5, name='Abgenommen', farbe='#0f4d26', art='abgeschlossen', pos=5)],
    prioritaeten=[dict(id=1, name='Hoch', farbe='#c0392b', pos=1), dict(id=2, name='Mittel', farbe='#e8a33d', pos=2), dict(id=3, name='Niedrig', farbe='#9fb3c8', pos=3)],
    kategorien=[dict(id=1, name='Mangel', farbe='#a3264f', pos=1), dict(id=2, name='Klärung', farbe='#5b8def', pos=2), dict(id=3, name='Material', farbe='#8a6d3b', pos=3), dict(id=4, name='Nachtrag', farbe='#7a3fa8', pos=4)],
    meilenstein_typen=[dict(id=i + 1, name=n, pos=i + 1) for i, n in enumerate(['Start Engineering', 'Abgabe 1. Revision', 'Start Anarbeitung', 'Start Schweißen', 'Start OT', 'Liefertermin (Fertigmeldung)', 'Auslieferung', 'Enddoku'])],
    budget_kategorien=[dict(id=1, name='Engineering', parent_id=None, pos=1), dict(id=2, name='Konstruktion', parent_id=1, pos=2), dict(id=3, name='AV', parent_id=1, pos=3), dict(id=4, name='Dokumentation', parent_id=1, pos=4),
                       dict(id=5, name='Anarbeitung', parent_id=None, pos=5), dict(id=6, name='Zusammenbau', parent_id=None, pos=6), dict(id=7, name='Schweißen', parent_id=None, pos=7), dict(id=8, name='WIG', parent_id=7, pos=8), dict(id=9, name='MAG', parent_id=7, pos=9),
                       dict(id=10, name='QS', parent_id=None, pos=10), dict(id=11, name='ZFP', parent_id=None, pos=11), dict(id=12, name='OT', parent_id=None, pos=12)],
    status_angebot=[dict(id=1, name='Entwurf', farbe='#d0d7e2', art='offen', pos=1), dict(id=2, name='Versendet', farbe='#1f6feb', art='offen', pos=2), dict(id=3, name='Nachgefasst', farbe='#f2b600', art='offen', pos=3),
                    dict(id=4, name='Beauftragt', farbe='#2b7a3d', art='abgeschlossen', pos=4), dict(id=5, name='Abgelehnt', farbe='#b3261e', art='abgeschlossen', pos=5), dict(id=6, name='Zurückgezogen', farbe='#6b7380', art='abgeschlossen', pos=6)],
)
PROJ = [dict(id=1, nummer='2026-001-00', bezeichnung='Beispielprojekt (Pilot)', kunde='Beispielkunde', ort='Werk 1', status='aktiv', pm_ids=[2, 3]),
        dict(id=2, nummer='2026-002-00', bezeichnung='Beispiel Wartung', kunde='Beispielkunde', ort='', status='aktiv', pm_ids=[3])]
BG = [dict(id=1, projekt_id=1, nummer='2026-001-01', bezeichnung='Behälter 2000 l', menge=3, sn_trenn='.', sn_art='GROSS', bauteile=[dict(id=1, bezeichnung='Mantel', zeichnung='Z-1001', menge=1), dict(id=2, bezeichnung='Klöpperboden', zeichnung='Z-1002', menge=2)]),
      dict(id=2, projekt_id=1, nummer='2026-001-02', bezeichnung='Bühne', menge=1, sn_trenn='.', sn_art='GROSS', bauteile=[]),
      dict(id=3, projekt_id=1, nummer='2026-001-03', bezeichnung='Rohrleitung', menge=2, sn_trenn='.', sn_art='GROSS', bauteile=[]),
      dict(id=4, projekt_id=2, nummer='2026-002-01', bezeichnung='Rührwerk Revision', menge=1, sn_trenn='.', sn_art='GROSS', bauteile=[])]
SN = []
for b in BG:
    for i in range(b['menge']):
        SN.append(dict(id=len(SN) + 1, baugruppe_id=b['id'], bauteil_id=None, sn=b['nummer'] + '.' + chr(65 + i), status_text=''))
TITLES = [('Schweißnaht Stutzen N3 nacharbeiten', 'Porosität bei Sichtprüfung festgestellt.\nNach VT erneut prüfen.', 1, 1, 4, -6, 1, 1),
          ('Zeichnung Bühnengeländer Rev. B freigeben', 'Kunde wartet auf Rev. B', 2, 2, 2, -2, 2, 2),
          ('Flanschdichtungen DN100 bestellen', 'PTFE, 8 Stück', 3, 4, 2, 3, None, 1),
          ('Wanddickenmessung Mantel dokumentieren', '', 2, 5, 1, 1, 1, 2),
          ('Beizen & Passivieren terminieren', 'OT-Partner anfragen', 3, None, 1, 5, 1, 1),
          ('Durchstrahlungsprüfung RT 10 %', 'ZFP-Dienstleister beauftragen', 2, 4, 1, 12, 1, 1),
          ('Klärung Stutzenlage N5 mit Kunde', '', 1, 2, 2, -12, 3, 2),
          ('Geländer Höhe 1100 statt 1000', 'Nachtrag prüfen', 4, 3, 1, 9, 2, 3),
          ('Rohrbögen 3D fehlen', 'Lieferant meldet Verzug', 3, 5, 3, -1, 3, 2),
          ('Druckprobe Protokoll', '', 2, 4, 2, 0, 1, 4),
          ('Schweißerprüfbescheinigung aktualisieren', '', None, 1, 3, 20, None, 1),
          ('Typenschild bestellen', '', 3, None, None, None, 1, 1),
          ('Aufmaß Bühne vor Ort', '', 2, 2, 2, 2, 2, 2),
          ('Mannloch Dichtfläche', 'Kratzer, nacharbeiten', 1, 4, 1, -3, 1, 1),
          ('Enddoku Gliederung', '', 2, 3, 3, 30, None, 1),
          ('Flansch DN50 falsche Bohrung', '', 1, 5, 1, -20, 3, 4),
          ('Isolierung Angebot einholen', '', 3, 3, 2, 6, 3, 1),
          ('Wartungsintervall festlegen', '', 2, 3, 3, 4, None, 1)]
OPL = []
for i, (t, d, kat, ver, prio, fr, bg, st) in enumerate(TITLES):
    pid = 2 if i == 17 else 1
    bgid = 4 if pid == 2 else bg
    sn = next((s for s in SN if s['baugruppe_id'] == bgid), None) if bgid == 1 and i % 2 == 0 else None
    OPL.append(dict(id=i + 1, nr=i + 1, projekt_id=pid, baugruppe_id=bgid, sn_id=sn['id'] if sn else None, titel=t, beschreibung=d, kategorie_id=kat, verantwortlich_id=ver,
                    prioritaet_id=prio, frist=D(fr) if fr is not None else None, status_id=st if i not in (9, 11) else (4 if i == 9 else 5), erstellt_von=2, erstellt_am=NOW(),
                    geaendert_am=(dt.datetime.now() - dt.timedelta(hours=i * 7)).isoformat(timespec='seconds'), version=1))
KOMM = [dict(id=1, opl_id=1, user_id=4, text='Habe mir das angesehen – 3 Poren, Nacharbeit morgen früh.', zeit=(dt.datetime.now() - dt.timedelta(hours=5)).isoformat(timespec='seconds')),
        dict(id=2, opl_id=1, user_id=2, text='Danke! Bitte danach Foto hochladen.', zeit=(dt.datetime.now() - dt.timedelta(hours=2)).isoformat(timespec='seconds'))]
MS = [dict(id=i + 1, projekt_id=1, baugruppe_id=None, typ_id=i + 1, datum=D(o), erledigt=1 if o < -5 else 0) for i, o in enumerate([-60, -30, -14, -3, 10, 25, 32, 45])]
ANG = [dict(id=1, nummer='2026-001-N1', art='nachtrag', projekt_id=1, bezeichnung='Nachtrag Geländerhöhe', kunde='Beispielkunde', eigentuemer_id=2, status_id=2, betrag=4800.0, versendet_am=D(-10), wiedervorlage=D(-1), freigaben=[3]),
       dict(id=2, nummer='2026-A02-00', art='angebot', projekt_id=None, bezeichnung='Lagertank 10 m³', kunde='Neukunde GmbH', eigentuemer_id=3, status_id=1, betrag=86500.0, versendet_am=None, wiedervorlage=D(3), freigaben=[])]

def users_by(i): return next((u for u in USERS if u['id'] == i), None)
def sd(name, i): return next((x for x in SD[name] if x['id'] == i), None)
def proj(i): return next(p for p in PROJ if p['id'] == i)
def bg(i): return next((b for b in BG if b['id'] == i), None)
def opl_item(o):
    st = sd('status_opl', o['status_id'])
    done = st['art'] == 'abgeschlossen'
    b = bg(o['baugruppe_id']); s = next((x for x in SN if x['id'] == o['sn_id']), None)
    return dict(o, projekt_nummer=proj(o['projekt_id'])['nummer'], baugruppe_nummer=b and b['nummer'], baugruppe_bezeichnung=b and b['bezeichnung'], sn=s and s['sn'],
                verantwortlich_name=(users_by(o['verantwortlich_id']) or {}).get('name'), status=st, prioritaet=sd('prioritaeten', o['prioritaet_id']), kategorie=sd('kategorien', o['kategorie_id']),
                ueberfaellig=bool(o['frist'] and o['frist'] < T.isoformat() and not done), kommentare_anzahl=sum(1 for k in KOMM if k['opl_id'] == o['id']), dateien_anzahl=0,
                erstellt_von_name=users_by(o['erstellt_von'])['name'])
def is_open(o): return sd('status_opl', o['status_id'])['art'] == 'offen'
def proj_summary(p):
    items = [o for o in OPL if o['projekt_id'] == p['id']]
    nm = next((dict(name=sd('meilenstein_typen', m['typ_id'])['name'], datum=m['datum']) for m in sorted(MS, key=lambda m: m['datum']) if m['projekt_id'] == p['id'] and not m['erledigt']), None)
    return dict(p, pms=[dict(id=u, name=users_by(u)['name']) for u in p['pm_ids']], offen=sum(is_open(o) for o in items), gesamt=len(items), erledigt=sum(not is_open(o) for o in items),
                ueberfaellig=sum(opl_item(o)['ueberfaellig'] for o in items), naechster_meilenstein=nm)
ACT = [dict(id=i, zeit=(dt.datetime.now() - dt.timedelta(minutes=17 * i + 3)).isoformat(timespec='seconds'), user_id=u, user_name=users_by(u)['name'], objekt=ob, objekt_id=oid, projekt_id=1, projekt_nummer='2026-001-00', aktion=a, details=det, titel=OPL[oid - 1]['titel'])
       for i, (u, ob, oid, a, det) in enumerate([(4, 'kommentar', 1, 'kommentiert', {'text': 'Habe mir das angesehen – 3 Poren'}), (3, 'opl', 2, 'status', {'status': 'In Arbeit'}), (5, 'opl', 9, 'geaendert', {'felder': ['frist', 'verantwortlich_id']}), (1, 'opl', 16, 'angelegt', {})])]

class H(SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=WEB, **k)
    def log_message(s, *a): pass
    def j(s, data, code=200):
        b = json.dumps(data, ensure_ascii=False).encode(); s.send_response(code); s.send_header('Content-Type', 'application/json; charset=utf-8'); s.send_header('Content-Length', len(b)); s.end_headers(); s.wfile.write(b)
    def body(s):
        n = int(s.headers.get('Content-Length') or 0); raw = s.rfile.read(n) if n else b''
        try: return json.loads(raw or b'{}')
        except Exception: return {}
    def authed(s): return 'opl_session=ok' in (s.headers.get('Cookie') or '')
    def do_GET(s): s.route('GET')
    def do_POST(s): s.route('POST')
    def do_PUT(s): s.route('PUT')
    def do_DELETE(s): s.route('DELETE')
    def route(s, m):
        u = urlparse(s.path); p = u.path; q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not p.startswith('/api/'):
            if m == 'GET': return super().do_GET()
            return s.j({'error': 'nicht gefunden'}, 404)
        p = p[4:]
        if p == '/login' and m == 'POST':
            b = s.body(); usr = next((x for x in USERS if x['login'] == b.get('login')), None)
            if not usr or b.get('passwort') != 'opl2026': return s.j({'error': 'Login oder Passwort falsch.'}, 401)
            data = json.dumps({'user': usr}).encode(); s.send_response(200); s.send_header('Content-Type', 'application/json'); s.send_header('Set-Cookie', 'opl_session=ok; Path=/; HttpOnly'); s.send_header('Set-Cookie', f'opl_uid={usr["id"]}; Path=/'); s.send_header('Content-Length', len(data)); s.end_headers(); s.wfile.write(data); return
        if not s.authed(): return s.j({'error': 'Bitte anmelden.'}, 401)
        uid = int(re.search(r'opl_uid=(\d+)', s.headers.get('Cookie') or 'opl_uid=2').group(1)); me = users_by(uid)
        if p == '/logout': return s.j({'ok': True})
        if p == '/me': return s.j({'user': me, 'seit': (dt.datetime.now() - dt.timedelta(hours=20)).isoformat(timespec='seconds')})
        if p == '/me/urlaub': me['urlaub'] = 1 if s.body().get('urlaub') else 0; return s.j({'ok': True})
        if p == '/me/passwort': return s.j({'ok': True})
        if p == '/rev': return s.j({'rev': rev[0]})
        if p == '/stammdaten': return s.j(dict(SD, users=[dict(id=u['id'], name=u['name'], rolle=u['rolle']) for u in USERS]))
        if p.startswith('/einstellungen/'):
            name = p.split('/')[-1]; b = s.body(); SD[name] = [dict(x, id=x.get('id') or 100 + i) for i, x in enumerate(b.get('eintraege', []))]; rev[0] += 1; return s.j({'ok': True})
        if p == '/dashboard':
            mine = [opl_item(o) for o in OPL if o['verantwortlich_id'] == uid and is_open(o)]
            mine.sort(key=lambda o: o['frist'] or '9999')
            op = [opl_item(o) for o in OPL if is_open(o)]
            return s.j(dict(kennzahlen=dict(offen=len(mine), ueberfaellig=sum(o['ueberfaellig'] for o in mine), woche=sum(1 for o in mine if o['frist'] and o['frist'] <= D(7)), erledigt_7t=2),
                            seit_letztem_besuch=ACT, meine_opl=mine, wiedervorlagen=[a for a in ANG if a['eigentuemer_id'] == uid],
                            projekte=[proj_summary(x) for x in PROJ], team=[dict(user=dict(id=u['id'], name=u['name']), offen=sum(1 for o in op if o['verantwortlich_id'] == u['id']), ueberfaellig=sum(1 for o in op if o['verantwortlich_id'] == u['id'] and o['ueberfaellig'])) for u in USERS],
                            ohne_verantwortlich=[o for o in op if not o['verantwortlich_id']], ohne_frist=[o for o in op if not o['frist']], liegengeblieben=op[-2:]))
        if p == '/dashboard/gesehen': return s.j({'ok': True})
        if p == '/projekte' and m == 'GET':
            r = [proj_summary(x) for x in PROJ if (not q.get('status') or x['status'] == q['status']) and (q.get('q', '').lower() in (x['nummer'] + x['bezeichnung'] + x['kunde']).lower())]
            return s.j(r)
        mm = re.match(r'^/projekte/(\d+)$', p)
        if mm:
            pr = proj(int(mm.group(1)))
            bgs = [dict(b, seriennummern=[dict(sn, offen=sum(1 for o in OPL if o['sn_id'] == sn['id'] and is_open(o))) for sn in SN if sn['baugruppe_id'] == b['id']]) for b in BG if b['projekt_id'] == pr['id']]
            items = [opl_item(o) for o in OPL if o['projekt_id'] == pr['id']]
            budgets = [dict(baugruppe_id=b['id'], kategorie_id=k, stunden=h, betrag=h * 68) for b in bgs for k, h in [(2, 40 + b['id'] * 10), (3, 12), (5, 30 * b['menge']), (6, 24), (8, 18 * b['menge']), (9, 30), (10, 8), (11, 6), (12, 10)]] if pr['id'] == 1 else []
            return s.j(dict(projekt=pr, pms=[dict(id=u, name=users_by(u)['name']) for u in pr['pm_ids']], baugruppen=bgs, meilensteine=[x for x in MS if x['projekt_id'] == pr['id']],
                            budgets=budgets if uid in pr['pm_ids'] or uid == 1 else None, opl_zaehler=dict(offen=sum(is_open(o) for o in OPL if o['projekt_id'] == pr['id']), ueberfaellig=sum(o['ueberfaellig'] for o in items), woche=sum(1 for o in items if o['frist'] and T.isoformat() <= o['frist'] <= D(7) and is_open(o)), erledigt=sum(not is_open(o) for o in OPL if o['projekt_id'] == pr['id'])),
                            nachtraege=[dict(a, status=sd('status_angebot', a['status_id'])) for a in ANG if a['art'] == 'nachtrag' and a['projekt_id'] == pr['id']],
                            verlauf=ACT))
        if re.match(r'^/projekte/\d+/pms$', p): pr = proj(int(p.split('/')[2])); pr['pm_ids'] = s.body().get('pm_ids', pr['pm_ids']); rev[0] += 1; return s.j({'ok': True})
        if p == '/meilensteine': b = s.body(); x = next((x for x in MS if x['projekt_id'] == b['projekt_id'] and x['typ_id'] == b['typ_id']), None); (x.update(datum=b['datum'], erledigt=b['erledigt']) if x else MS.append(dict(b, id=len(MS) + 1))); rev[0] += 1; return s.j({'ok': True})
        if p == '/opl' and m == 'GET':
            r = [opl_item(o) for o in OPL]
            for k in ('projekt_id', 'baugruppe_id', 'status_id', 'prioritaet_id', 'kategorie_id'):
                if q.get(k): r = [o for o in r if str(o.get(k)) == q[k]]
            if q.get('verantwortlich_id'): r = [o for o in r if str(o['verantwortlich_id'] or 0) == q['verantwortlich_id']]
            sa = q.get('status_art', 'alle')
            if sa != 'alle' and not q.get('status_id'): r = [o for o in r if o['status']['art'] == sa]
            if q.get('ueberfaellig'): r = [o for o in r if o['ueberfaellig']]
            if q.get('q'): r = [o for o in r if q['q'].lower() in (o['titel'] + (o['beschreibung'] or '') + (o['sn'] or '')).lower()]
            srt = q.get('sort', 'frist')
            key = {'frist': lambda o: o['frist'] or '9999', 'nr': lambda o: o['nr'], 'prioritaet': lambda o: o['prioritaet_id'] or 9, '-geaendert_am': lambda o: o['geaendert_am']}.get(srt, lambda o: o['nr'])
            r.sort(key=key, reverse=srt.startswith('-'))
            return s.j({'items': r, 'gesamt': len(r)})
        if p == '/opl' and m == 'POST':
            b = s.body(); o = dict(id=len(OPL) + 1, nr=len(OPL) + 1, projekt_id=b['projekt_id'], baugruppe_id=b.get('baugruppe_id'), sn_id=b.get('sn_id'), titel=b['titel'], beschreibung=b.get('beschreibung', ''), kategorie_id=b.get('kategorie_id'), verantwortlich_id=b.get('verantwortlich_id'), prioritaet_id=b.get('prioritaet_id') or 2, frist=b.get('frist'), status_id=1, erstellt_von=uid, erstellt_am=NOW(), geaendert_am=NOW(), version=1)
            OPL.append(o); rev[0] += 1; return s.j({'item': opl_item(o)})
        if p == '/opl/bulk':
            b = s.body()
            for o in OPL:
                if o['id'] in b['ids']: o.update(b['changes']); o['geaendert_am'] = NOW()
            rev[0] += 1; return s.j({'ok': True, 'anzahl': len(b['ids'])})
        mm = re.match(r'^/opl/(\d+)$', p)
        if mm:
            o = next(x for x in OPL if x['id'] == int(mm.group(1)))
            if m == 'GET': return s.j(dict(item=opl_item(o), kommentare=[dict(k, user_name=users_by(k['user_id'])['name']) for k in KOMM if k['opl_id'] == o['id']], dateien=[], verlauf=[a for a in ACT if a['objekt_id'] == o['id']]))
            if m == 'PUT':
                b = s.body(); ch = b.get('changes', {}); base = b.get('base', {})
                bad = [k for k, v in ch.items() if o.get(k) != base.get(k) and o.get(k) != v]
                if bad: return s.j({'error': 'Konflikt', 'felder': bad, 'item': opl_item(o), 'von': 'Mitarbeiter 1', 'am': o['geaendert_am']}, 409)
                o.update(ch); o['geaendert_am'] = NOW(); rev[0] += 1; return s.j({'item': opl_item(o)})
            if m == 'DELETE': OPL.remove(o); rev[0] += 1; return s.j({'ok': True})
        mm = re.match(r'^/opl/(\d+)/kommentare$', p)
        if mm: k = dict(id=len(KOMM) + 1, opl_id=int(mm.group(1)), user_id=uid, text=s.body().get('text'), zeit=NOW()); KOMM.append(k); rev[0] += 1; return s.j({'kommentar': dict(k, user_name=me['name'])})
        if p == '/kalender':
            r = [dict(typ='opl', id=o['id'], datum=o['frist'], titel=o['titel'], projekt_nummer=o['projekt_nummer'], projekt_id=o['projekt_id'], farbe=o['status']['farbe'], ueberfaellig=o['ueberfaellig'], erledigt=not is_open(o)) for o in map(opl_item, OPL) if o['frist']]
            r += [dict(typ='meilenstein', id=x['id'], datum=x['datum'], titel=sd('meilenstein_typen', x['typ_id'])['name'], projekt_nummer=proj(x['projekt_id'])['nummer'], projekt_id=x['projekt_id'], farbe='#0a57b0', ueberfaellig=x['datum'] < T.isoformat() and not x['erledigt'], erledigt=bool(x['erledigt'])) for x in MS]
            r += [dict(typ='wiedervorlage', id=a['id'], datum=a['wiedervorlage'], titel=a['bezeichnung'], projekt_nummer=a['nummer'], farbe='#7a3fa8', ueberfaellig=a['wiedervorlage'] < T.isoformat(), erledigt=False) for a in ANG if a['wiedervorlage']]
            if q.get('projekt_id'): r = [x for x in r if str(x.get('projekt_id')) == q['projekt_id']]
            return s.j([x for x in r if q.get('von', '0') <= x['datum'] <= q.get('bis', '9')])
        if p == '/kalender/verschieben':
            b = s.body(); src = {'opl': (OPL, 'frist'), 'meilenstein': (MS, 'datum'), 'wiedervorlage': (ANG, 'wiedervorlage')}[b['typ']]
            next(x for x in src[0] if x['id'] == b['id'])[src[1]] = b['datum']; rev[0] += 1; return s.j({'ok': True})
        if p == '/angebote' and m == 'GET':
            r = [dict(a, eigentuemer_name=users_by(a['eigentuemer_id'])['name'], status=sd('status_angebot', a['status_id']), projekt_nummer=a['projekt_id'] and proj(a['projekt_id'])['nummer'], urlaub_sichtbar=False, privat=not a['freigaben']) for a in ANG]
            if q.get('art'): r = [a for a in r if a['art'] == q['art']]
            return s.j(r)
        if p == '/angebote' and m == 'POST': b = s.body(); a = dict(b, id=len(ANG) + 1, nummer=b.get('nummer') or f'2026-A0{len(ANG)+1}-00', eigentuemer_id=uid, freigaben=[], versendet_am=None); ANG.append(a); rev[0] += 1; return s.j({'angebot': a})
        mm = re.match(r'^/angebote/(\d+)(/.*)?$', p)
        if mm:
            a = next(x for x in ANG if x['id'] == int(mm.group(1))); sub = mm.group(2) or ''
            if sub == '/freigaben': a['freigaben'] = s.body()['user_ids']; return s.j({'ok': True})
            if sub == '/umwandeln/vorschau':
                b = s.body(); pn = proj(b['projekt_id'])['nummer'] if b.get('ziel') == 'bestehend' else (b.get('nummer') or '2026-003-00')
                start = 1 + (sum(1 for x in BG if x['nummer'].startswith(pn[:8])) if b.get('ziel') == 'bestehend' else 0)
                return s.j(dict(projekt_nummer=pn, zuordnung=[dict(quelle=a['nummer'][:8] + f'-0{i+1}', bezeichnung=n, neue_nummer=pn[:8] + f'-{start+i:02d}') for i, n in enumerate(['Tank', 'Stützen'])]))
            if sub == '/umwandeln': return s.j({'projekt_id': 1})
            if m == 'GET': return s.j(dict(a, eigentuemer_name=users_by(a['eigentuemer_id'])['name'], freigaben=[dict(id=f) for f in a['freigaben']]))
            if m == 'PUT': a.update(s.body().get('changes', {})); rev[0] += 1; return s.j({'angebot': a})
            if m == 'DELETE': ANG.remove(a); return s.j({'ok': True})
        if p == '/suche':
            ql = q.get('q', '').split(); words = [w for w in ql if ':' not in w]
            hits = [o for o in map(opl_item, OPL) if all(w.lower() in (o['titel'] + o['beschreibung']).lower() for w in words)][:8]
            def mk(t):
                for w in words: t = re.sub('(' + re.escape(w) + ')', r'<mark>\1</mark>', t, flags=re.I)
                return t
            return s.j({'gruppen': [dict(art='opl', label='Offene Punkte', treffer=[dict(ref_id=o['id'], titel=mk(o['titel']), ausschnitt=mk(o['beschreibung'] or ''), projekt_nummer=o['projekt_nummer'], link='/opl/%d' % o['id']) for o in hits]),
                                    dict(art='projekt', label='Projekte', treffer=[dict(ref_id=x['id'], titel=mk(x['bezeichnung']), ausschnitt=x['nummer'], projekt_nummer=x['nummer'], link='/projekte/%d' % x['id']) for x in PROJ if all(w.lower() in x['bezeichnung'].lower() for w in words)])]})
        if p.startswith('/dateien') or p.startswith('/import'):
            return s.j({'error': 'Im Mock nicht verfügbar'}, 501)
        return s.j({'error': 'Unbekannte Adresse ' + p}, 404)

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f'Mock läuft: http://localhost:{port}  (Login pm1 / opl2026)')
    ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()

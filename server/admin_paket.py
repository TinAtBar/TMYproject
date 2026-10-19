"""Änderungspakete der Admin-Konsole (desktop-Agent).

Ein Paket bündelt Stammdaten-/Benutzer-/Zuordnungsänderungen, die erst geprüft
(Vorschau mit Auswirkungen) und dann atomar eingespielt werden – entweder über
den laufenden Server (POST /api/admin/paket) oder, wenn kein Server läuft,
direkt von der Admin-Konsole unter admin.lock.

Paketformat:
  {"id": "<uuid>", "beschreibung": "...", "autor": "admin", "erstellt": "<iso>",
   "ops": [ {"op": "liste", "liste": "status_opl", "eintraege": [...], "ersatz": {"<alt_id>": <neu_id>|"<key>"}},
            {"op": "benutzer", "eintraege": [{id?, login, name, rolle, aktiv, passwort?}]},
            {"op": "projekt_pms", "projekt_id": 1, "pm_ids": [2, 3]},
            {"op": "angebot_eigentuemer", "angebot_id": 4, "eigentuemer_id": 2},
            {"op": "einstellungen", "werte": {"sn_trenn": ".", "sn_art": "GROSS"}},
            {"op": "firma_setzen", "werte": {"<key>": <json>|null}},
            {"op": "ablage_global", "eintraege": [{id?, name, pfad, farbe}]} ]}   # R26-W: ersetzt alle globalen Ablagen
Listen-Einträge dürfen statt id einen "key" tragen (neu), parent_key verweist auf neue Eltern.

Nur Standardbibliothek; arbeitet auf einer sqlite3-Verbindung (Row-Factory egal).
"""
import json
import shutil
import sqlite3

LISTEN = {
    "status_opl": ("status_opl", ("name", "farbe", "art", "pos", "ist_start"), [("opl", "status_id", "Punkte")]),
    "prioritaeten": ("prioritaeten", ("name", "farbe", "pos"), [("opl", "prioritaet_id", "Punkte")]),
    "kategorien": ("kategorien", ("name", "farbe", "pos"), [("opl", "kategorie_id", "Punkte")]),
    "meilenstein_typen": ("meilenstein_typen", ("name", "pos", "gewicht"), [("meilensteine", "typ_id", "Meilensteine")]),
    "budget_kategorien": ("budget_kategorien", ("name", "parent_id", "pos"),
                          [("budgets", "kategorie_id", "Budgetwerte"), ("budget_kategorien", "parent_id", "Unterkategorien")]),
    "status_angebot": ("status_angebot", ("name", "farbe", "art", "pos"), [("angebote", "status_id", "Angebote")]),
}
LISTEN_NAMEN = {"status_opl": "Status", "prioritaeten": "Priorität", "kategorien": "Kategorie",
                "meilenstein_typen": "Meilenstein", "budget_kategorien": "Budgetkategorie",
                "status_angebot": "Angebotsstatus"}
ROLLEN = ("admin", "pm", "mitarbeiter", "controlling", "leiter")  # R26: + controlling, R29-F: + leiter
# R26-W: Listen, bei denen ein verwendeter Eintrag ohne Ersatz gelöscht werden darf – die Verweise werden gelöst
# (Projekt-Meilensteine behalten Name/Datum, typ_id wird NULL).
LOESEN_STATT_ERSETZEN = {"meilenstein_typen"}
EINSTELLUNGEN = {"sn_trenn": ".", "sn_art": "GROSS", "nummer_format": "JJJJ-NNN-NN", "firma": ""}


class PaketFehler(Exception):
    pass


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(conn, sql, args=()):
    r = _rows(conn, sql, args)
    return r[0] if r else None


def einstellungen_lesen(conn):
    werte = dict(EINSTELLUNGEN)
    for r in _rows(conn, "SELECT k, v FROM meta WHERE k LIKE 'cfg.%'"):
        werte[r["k"][4:]] = r["v"]
    return werte


# ---------------------------------------------------------------- Vorschau
def pruefen(conn, paket):
    """Gibt {"ok": bool, "auswirkungen": [str], "fehler": [str]} zurück – ohne etwas zu ändern."""
    aus, fehler = [], []
    ops = (paket or {}).get("ops") or []
    if not ops:
        fehler.append("Das Änderungspaket ist leer.")
    for op in ops:
        try:
            fn = _PRUEF.get(op.get("op"))
            if not fn:
                raise PaketFehler(f"Unbekannte Operation: {op.get('op')}")
            fn(conn, op, aus)
        except PaketFehler as e:
            fehler.append(str(e))
    return {"ok": not fehler, "auswirkungen": aus, "fehler": fehler}


def _liste_plan(conn, op):
    liste = op.get("liste")
    if liste not in LISTEN:
        raise PaketFehler(f"Unbekannte Liste: {liste}")
    table, felder, refs = LISTEN[liste]
    spalten = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    felder = tuple(f for f in felder if f in spalten)  # R26-W: z. B. gewicht erst ab Migration
    alt = {r["id"]: r for r in _rows(conn, f"SELECT * FROM {table}")}
    eintraege = op.get("eintraege") or []
    keys = {e.get("key") for e in eintraege if e.get("key")}
    behalten = set()
    for e in eintraege:
        if not (e.get("name") or "").strip():
            raise PaketFehler(f"{LISTEN_NAMEN[liste]}: Name darf nicht leer sein")
        if "gewicht" in felder and e.get("gewicht") is not None:  # R26-W
            try:
                g = float(str(e["gewicht"]).replace(",", "."))
            except ValueError:
                raise PaketFehler(f"{LISTEN_NAMEN[liste]} „{e['name']}“: Gewicht ist keine Zahl")
            if not 0 <= g <= 1000:
                raise PaketFehler(f"{LISTEN_NAMEN[liste]} „{e['name']}“: Gewicht 0–1000")
            e["gewicht"] = g
        if "art" in felder and e.get("art", "offen") not in ("offen", "abgeschlossen"):
            raise PaketFehler(f"{LISTEN_NAMEN[liste]} „{e['name']}“: ungültige Art")
        if e.get("id") in alt:
            behalten.add(e["id"])
    namen = [e["name"].strip().lower() for e in eintraege if e.get("parent_id") is None and not e.get("parent_key")]
    if liste != "budget_kategorien" and len(namen) != len(set(namen)):
        raise PaketFehler(f"{LISTEN_NAMEN[liste]}: Namen müssen eindeutig sein")
    if liste in ("status_opl", "status_angebot", "prioritaeten") and not eintraege:
        raise PaketFehler(f"{LISTEN_NAMEN[liste]}: mindestens ein Eintrag nötig")
    if liste == "status_opl":
        if not any(e.get("art", "offen") == "offen" for e in eintraege):
            raise PaketFehler("Status: mindestens ein offener Status nötig")
        if not any(e.get("art") == "abgeschlossen" for e in eintraege):
            raise PaketFehler("Status: mindestens ein abgeschlossener Status nötig")
    ersatz = {}
    for k, v in (op.get("ersatz") or {}).items():
        ersatz[int(k)] = v
    geloescht = []
    for aid in sorted(set(alt) - behalten):
        nutz = []
        for t, col, label in refs:
            n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (aid,)).fetchone()[0]
            if n:
                nutz.append((t, col, label, n))
        ziel = ersatz.get(aid)
        if nutz and ziel is None and liste not in LOESEN_STATT_ERSETZEN:
            raise PaketFehler(f"{LISTEN_NAMEN[liste]} „{alt[aid]['name']}“ wird noch verwendet "
                              f"({', '.join(f'{n} {lb}' for _, _, lb, n in nutz)}) – bitte Ersatz wählen")
        if ziel is not None and not ((isinstance(ziel, int) and ziel in behalten) or (isinstance(ziel, str) and ziel in keys)):
            raise PaketFehler(f"{LISTEN_NAMEN[liste]} „{alt[aid]['name']}“: Ersatz ist kein verbleibender Eintrag")
        geloescht.append((aid, nutz, ziel))
    return table, felder, refs, alt, eintraege, geloescht


def _name_fuer(eintraege, alt, ziel):
    if isinstance(ziel, int):
        for e in eintraege:
            if e.get("id") == ziel:
                return e["name"]
        return alt.get(ziel, {}).get("name", str(ziel))
    for e in eintraege:
        if e.get("key") == ziel:
            return e["name"]
    return str(ziel)


def _pruef_liste(conn, op, aus):
    table, felder, refs, alt, eintraege, geloescht = _liste_plan(conn, op)
    ln = LISTEN_NAMEN[op["liste"]]
    for e in eintraege:
        if e.get("id") in alt:
            a = alt[e["id"]]
            if a["name"] != e["name"]:
                aus.append(f"{ln} „{a['name']}“ wird umbenannt in „{e['name']}“")
            for f in ("farbe", "art", "gewicht"):
                if f in felder and f in e and a.get(f) != e.get(f):
                    aus.append(f"{ln} „{e['name']}“: {f} {a.get(f)} → {e.get(f)}")
        else:
            aus.append(f"{ln} „{e['name']}“ wird neu angelegt")
    for aid, nutz, ziel in geloescht:
        if nutz and ziel is None:  # R26-W: Verweise lösen
            for _, _, label, n in nutz:
                aus.append(f"{ln} „{alt[aid]['name']}“ wird gelöscht → {n} {label} behalten Name und Datum (ohne Standard-Bezug)")
        elif nutz:
            for _, _, label, n in nutz:
                aus.append(f"{ln} „{alt[aid]['name']}“ wird gelöscht → {n} {label} auf „{_name_fuer(eintraege, alt, ziel)}“")
        else:
            aus.append(f"{ln} „{alt[aid]['name']}“ wird gelöscht (nicht verwendet)")
    alte_reihe = [r["id"] for r in sorted(alt.values(), key=lambda r: (r["pos"], r["id"]))]
    neue_reihe = [e.get("id") for e in eintraege if e.get("id") in alt]
    if [i for i in alte_reihe if i in neue_reihe] != neue_reihe:
        aus.append(f"{ln}: Reihenfolge geändert")


def _pruef_benutzer(conn, op, aus):
    alt = {r["id"]: r for r in _rows(conn, "SELECT * FROM users")}
    logins = {}  # login.lower() -> {ids}  (Altbestand kann Dubletten in anderer Schreibweise haben)
    for r in alt.values():
        logins.setdefault(r["login"].lower(), set()).add(r["id"])
    endzustand = {i: dict(r) for i, r in alt.items()}
    for e in op.get("eintraege") or []:
        login = (e.get("login") or "").strip()
        if not login or not (e.get("name") or "").strip():
            raise PaketFehler("Benutzer: Login und Name sind Pflicht")
        if e.get("rolle") not in ROLLEN:
            raise PaketFehler(f"Benutzer {login}: ungültige Rolle")
        andere = logins.get(login.lower(), set()) - {e.get("id")}
        unveraendert = e.get("id") in alt and alt[e["id"]]["login"] == login
        if andere and not unveraendert:
            raise PaketFehler(f"Benutzer {login}: Login ist bereits vergeben")
        if e.get("passwort") is not None and 0 < len(e["passwort"]) < 6:
            raise PaketFehler(f"Benutzer {login}: Startpasswort mindestens 6 Zeichen")
        if (e.get("windows_login") or "").strip():  # R28-G1: Windows-Benutzer eindeutig
            import domaene
            wl = domaene.windows_login_bereinigen(e["windows_login"])
            hat = "windows_login" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            if hat and conn.execute("SELECT 1 FROM users WHERE windows_login=? COLLATE NOCASE AND id IS NOT ?",
                                    (wl, e.get("id"))).fetchone():
                raise PaketFehler(f"Benutzer {login}: Windows-Benutzer „{wl}“ ist bereits vergeben")
            if not e.get("id") or (alt.get(e["id"]) or {}).get("windows_login") != wl:
                aus.append(f"{e.get('name') or login}: Anmeldung mit Windows-Benutzer {wl}")
        if e.get("id"):
            a = alt.get(e["id"])
            if not a:
                raise PaketFehler(f"Benutzer-ID {e['id']} unbekannt")
            if a["rolle"] != e["rolle"]:
                pm_n = conn.execute("SELECT COUNT(*) FROM projekt_pm WHERE user_id=?", (a["id"],)).fetchone()[0]
                zus = f" (ist PM in {pm_n} Projekten – Zuordnung bleibt, Bearbeitungsrecht entfällt)" if pm_n and e["rolle"] == "mitarbeiter" else ""
                aus.append(f"Rolle von {a['name']}: {a['rolle']} → {e['rolle']}{zus}")
            if a["name"] != e["name"] or a["login"] != login:
                aus.append(f"Benutzer {a['login']} → Login {login}, Name {e['name']}")
            akt = 1 if e.get("aktiv", 1) else 0
            if a["aktiv"] != akt:
                if not akt:
                    n = conn.execute("SELECT COUNT(*) FROM opl o JOIN status_opl s ON s.id=o.status_id "
                                     "JOIN opl_zustaendig z ON z.opl_id=o.id WHERE z.user_id=? AND o.geloescht=0 AND s.art='offen'", (a["id"],)).fetchone()[0]
                    aus.append(f"{a['name']} wird deaktiviert" + (f" – hat noch {n} offene Punkte" if n else ""))
                else:
                    aus.append(f"{a['name']} wird wieder aktiviert")
            if e.get("passwort"):
                aus.append(f"{a['name']}: neues Startpasswort (muss bei Anmeldung geändert werden)")
            endzustand[e["id"]].update(rolle=e["rolle"], aktiv=akt)
        else:
            if not e.get("passwort") and not (e.get("windows_login") or "").strip():  # R28-G1: Windows-Benutzer ohne Startpasswort
                raise PaketFehler(f"Neuer Benutzer {login}: Startpasswort fehlt")
            aus.append(f"Neuer Benutzer {e['name']} ({login}, {e['rolle']}) – muss Passwort bei erster Anmeldung ändern")
            endzustand[f"neu-{login}"] = {"rolle": e["rolle"], "aktiv": 1 if e.get("aktiv", 1) else 0}
            logins.setdefault(login.lower(), set()).add(f"neu-{login}")
    if not any(u["rolle"] == "admin" and u["aktiv"] for u in endzustand.values()):
        raise PaketFehler("Es muss mindestens ein aktiver Administrator bleiben")


def _pruef_pms(conn, op, aus):
    p = _one(conn, "SELECT * FROM projekte WHERE id=?", (op.get("projekt_id"),))
    if not p:
        raise PaketFehler("Projekt nicht gefunden")
    ids = [int(i) for i in op.get("pm_ids") or []]
    if not ids:
        raise PaketFehler(f"Projekt {p['nummer']}: mindestens ein Projektleiter nötig")
    users = {r["id"]: r for r in _rows(conn, "SELECT id, name, rolle FROM users")}
    for i in ids:
        if i not in users or users[i]["rolle"] not in ("pm", "admin"):
            raise PaketFehler(f"Projekt {p['nummer']}: Benutzer {i} ist kein Projektleiter")
    alt = {r["user_id"] for r in _rows(conn, "SELECT user_id FROM projekt_pm WHERE projekt_id=?", (p["id"],))}
    for i in sorted(set(ids) - alt):
        aus.append(f"Projekt {p['nummer']}: {users[i]['name']} wird Projektleiter")
    for i in sorted(alt - set(ids)):
        aus.append(f"Projekt {p['nummer']}: {users.get(i, {}).get('name', i)} ist nicht mehr Projektleiter")


def _pruef_eigentuemer(conn, op, aus):
    a = _one(conn, "SELECT * FROM angebote WHERE id=?", (op.get("angebot_id"),))
    if not a:
        raise PaketFehler("Angebot nicht gefunden")
    u = _one(conn, "SELECT * FROM users WHERE id=?", (op.get("eigentuemer_id"),))
    if not u or u["rolle"] not in ("pm", "admin"):
        raise PaketFehler(f"Angebot {a['nummer']}: neuer Eigentümer muss Projektleiter sein")
    alt = _one(conn, "SELECT name FROM users WHERE id=?", (a["eigentuemer_id"],))
    if a["eigentuemer_id"] != u["id"]:
        aus.append(f"Angebot {a['nummer']}: Eigentümer {alt['name'] if alt else '—'} → {u['name']}")


def _pruef_einst(conn, op, aus):
    alt = einstellungen_lesen(conn)
    for k, v in (op.get("werte") or {}).items():
        if k not in EINSTELLUNGEN:
            raise PaketFehler(f"Unbekannte Einstellung: {k}")
        if k == "sn_art" and v not in ("GROSS", "klein", "zahl", "frei"):
            raise PaketFehler("SN-Schema: ungültige Art")
        if str(alt.get(k)) != str(v):
            aus.append(f"Einstellung {k}: „{alt.get(k)}“ → „{v}“ (gilt für neue Baugruppen)")


def _pruef_firma(conn, op, aus):  # R26-F: Firmeneinstellungen (Tabelle firma_einstellungen)
    import re as _re
    import firma
    werte = op.get("werte")
    if not isinstance(werte, dict) or not werte:
        raise PaketFehler("Firmeneinstellungen: keine Werte angegeben")
    for k, v in werte.items():
        if not isinstance(k, str) or not _re.fullmatch(r"[a-z0-9_.\-]{1,80}", k):
            raise PaketFehler(f"Firmeneinstellung: ungültiger Schlüssel „{k}“")
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            raise PaketFehler(f"Firmeneinstellung {k}: Wert nicht speicherbar")
        alt = firma.get(conn, k)
        if alt != v:
            zeig = "••••" if any(w in k for w in ("token", "passwort", "kennwort")) else json.dumps(v, ensure_ascii=False)[:80]
            aus.append(f"Firmeneinstellung {k}: " + ("entfernt" if v is None else f"→ {zeig}"))


def _data_dir(conn):
    """Ordner der geöffneten Datenbank (= Datenordner von Barlage PM) oder None."""
    import os
    try:
        for r in conn.execute("PRAGMA database_list"):
            if r[1] == "main" and r[2]:
                return os.path.dirname(r[2])
    except sqlite3.Error:
        pass
    return None


def _ablage_global_sauber(conn, op):  # R26-W: globale eigene Ablagen (ablage_eigene, projekt_id NULL)
    import os
    import ablage
    eintraege = op.get("eintraege")
    if not isinstance(eintraege, list):
        raise PaketFehler("Globale Ablagen: Liste erwartet")
    alt = {r["id"]: r for r in _rows(conn, "SELECT * FROM ablage_eigene WHERE projekt_id IS NULL")}
    out = []
    for e in eintraege:
        name = str(e.get("name") or "").strip()[:80]
        pfad = str(e.get("pfad") or "").strip()
        if not name or not pfad:
            raise PaketFehler("Globale Ablage: Name und Pfad sind nötig")
        if not (pfad.startswith("\\\\") or os.path.isabs(pfad) or (len(pfad) > 2 and pfad[1] == ":")):
            raise PaketFehler(f"Globale Ablage „{name}“: bitte vollständigen Pfad angeben (z. B. \\\\server\\freigabe)")
        daten = _data_dir(conn)
        if daten and ablage.innerhalb(str(daten), pfad):
            raise PaketFehler(f"Globale Ablage „{name}“: der Datenordner von Barlage PM ist nicht erlaubt")
        i = e.get("id")
        if i is not None and i not in alt:
            raise PaketFehler(f"Globale Ablage „{name}“: unbekannte id {i}")
        out.append({"id": i, "name": name, "pfad": pfad, "farbe": ablage.farbe_ok(e.get("farbe")) or "aqua"})
    return alt, out


def _pruef_ablage_global(conn, op, aus):
    alt, neu = _ablage_global_sauber(conn, op)
    ids = {e["id"] for e in neu if e["id"] is not None}
    for e in neu:
        a = alt.get(e["id"])
        if not a:
            aus.append(f"Globale Ablage „{e['name']}“ wird angelegt ({e['pfad']})")
        elif (a["name"], a["pfad"], a["farbe"]) != (e["name"], e["pfad"], e["farbe"]):
            aus.append(f"Globale Ablage „{a['name']}“ wird geändert")
    for i, a in alt.items():
        if i not in ids:
            aus.append(f"Globale Ablage „{a['name']}“ wird entfernt (Dateien bleiben unberührt)")
    if [e["id"] for e in neu if e["id"] in alt] != [i for i in sorted(alt, key=lambda x: (alt[x]["pos"] or 0, x)) if i in ids]:
        aus.append("Globale Ablagen: Reihenfolge geändert")


def _anw_ablage_global(conn, op, hash_pw):
    alt, neu = _ablage_global_sauber(conn, op)
    ids = {e["id"] for e in neu if e["id"] is not None}
    for i in alt:
        if i not in ids:
            conn.execute("DELETE FROM ablage_eigene WHERE id=? AND projekt_id IS NULL", (i,))
    for pos, e in enumerate(neu):
        if e["id"] is not None:
            conn.execute("UPDATE ablage_eigene SET name=?, pfad=?, farbe=?, pos=? WHERE id=?", (e["name"], e["pfad"], e["farbe"], pos, e["id"]))
        else:
            conn.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe,pos,erstellt_von,erstellt_am) VALUES(NULL,?,?,?,?,NULL,?)",
                         (e["name"], e["pfad"], e["farbe"], pos, _jetzt()))


def _vertr_sauber(conn, op):  # R27-105: Vertretungen (Admin-Konsole)
    import vertretung
    from util import ApiError
    neu, ende = [], []
    for e in op.get("neu") or []:
        try:
            neu.append(vertretung.pruefen(conn, e, None))
        except ApiError as ex:
            raise PaketFehler(f"Vertretung: {ex.msg}")
    for i in op.get("beenden") or []:
        if not conn.execute("SELECT 1 FROM vertretungen WHERE id=?", (int(i),)).fetchone():
            raise PaketFehler(f"Vertretung {i} gibt es nicht")
        ende.append(int(i))
    return neu, ende


def _vertr_name(conn, uid):
    r = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return r[0] if r else "?"


def _pruef_vertretungen(conn, op, aus):
    neu, ende = _vertr_sauber(conn, op)
    for d in neu:
        wer = _vertr_name(conn, d["vertretener_user_id"]) if d["vertretener_user_id"] else "Rolle " + d["vertretener_rolle"]
        aus.append(f"Vertretung: {_vertr_name(conn, d['vertreter_user_id'])} vertritt {wer} ({d['bereich']}) "
                   f"vom {d['von']} bis {d['bis']}")
    for i in ende:
        aus.append(f"Vertretung {i} wird beendet")


def _anw_vertretungen(conn, op, hash_pw):
    import datetime as _dt
    import vertretung
    neu, ende = _vertr_sauber(conn, op)
    heute = _dt.date.today().isoformat()
    gestern = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    for i in ende:
        conn.execute("DELETE FROM vertretungen WHERE id=? AND von>?", (i, heute))
        conn.execute("UPDATE vertretungen SET bis=? WHERE id=? AND bis>=?", (gestern, i, heute))
    for d in neu:
        vertretung.einfuegen(conn, d, None)


_PRUEF = {"liste": _pruef_liste, "benutzer": _pruef_benutzer, "projekt_pms": _pruef_pms,
          "angebot_eigentuemer": _pruef_eigentuemer, "einstellungen": _pruef_einst, "firma_setzen": _pruef_firma,
          "ablage_global": _pruef_ablage_global, "vertretungen": _pruef_vertretungen}


# ---------------------------------------------------------------- Anwenden
def anwenden(conn, paket, hash_pw, user_id=None, now=None):
    """Spielt das Paket in der bereits offenen Transaktion ein. Wirft PaketFehler bei Problemen.

    hash_pw: Funktion pw -> (hash, salt) aus auth.py.
    """
    v = pruefen(conn, paket)
    if not v["ok"]:
        raise PaketFehler("; ".join(v["fehler"]))
    for op in paket["ops"]:
        _ANW[op["op"]](conn, op, hash_pw)
    conn.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,?,?,?,?,?,?)",
                 (now or _jetzt(), user_id, "einstellung", None, None, "geaendert",
                  json.dumps({"titel": "Änderungspaket: " + (paket.get("beschreibung") or paket.get("id") or ""),
                              "paket_id": paket.get("id"), "auswirkungen": v["auswirkungen"][:50]}, ensure_ascii=False)))
    return v


def _jetzt():
    import datetime as _dt
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _anw_liste(conn, op, hash_pw):
    table, felder, refs, alt, eintraege, geloescht = _liste_plan(conn, op)
    key_ids = {}
    behalten = set()
    for pos, e in enumerate(eintraege):
        werte = {f: e.get(f) for f in felder if f in e and f != "parent_id"}
        werte["pos"] = pos
        if "parent_id" in felder:
            werte["parent_id"] = e.get("parent_id")
        if e.get("id") in alt:
            sets = ", ".join(f"{f}=?" for f in werte)
            conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*werte.values(), e["id"]))
            neu_id = e["id"]
        else:
            cols = ", ".join(werte)
            neu_id = conn.execute(f"INSERT INTO {table}({cols}) VALUES({', '.join('?' * len(werte))})",
                                  tuple(werte.values())).lastrowid
        behalten.add(neu_id)
        if e.get("key"):
            key_ids[e["key"]] = neu_id
        e["_id"] = neu_id
    if "parent_id" in felder:
        for e in eintraege:
            if e.get("parent_key"):
                conn.execute(f"UPDATE {table} SET parent_id=? WHERE id=?", (key_ids.get(e["parent_key"]), e["_id"]))
    for aid, nutz, ziel in geloescht:
        zid = key_ids.get(ziel) if isinstance(ziel, str) else ziel
        if ziel is None and nutz and op["liste"] == "meilenstein_typen":  # R26-W: Projektzeilen vom Typ lösen
            conn.execute("UPDATE meilensteine SET name=COALESCE(name, ?), typ_id=NULL WHERE typ_id=?", (alt[aid]["name"], aid))
        if ziel is not None:
            for t, col, _ in refs:
                conn.execute(f"UPDATE {t} SET {col}=? WHERE {col}=?", (zid, aid))
        conn.execute(f"DELETE FROM {table} WHERE id=?", (aid,))
    if op["liste"] == "status_opl":
        starts = [r[0] for r in conn.execute("SELECT id FROM status_opl WHERE ist_start=1 ORDER BY pos")]
        if len(starts) != 1:
            conn.execute("UPDATE status_opl SET ist_start=0")
            sid = starts[0] if starts else conn.execute(
                "SELECT id FROM status_opl WHERE art='offen' ORDER BY pos LIMIT 1").fetchone()[0]
            conn.execute("UPDATE status_opl SET ist_start=1 WHERE id=?", (sid,))
    for e in eintraege:
        e.pop("_id", None)


def _anw_benutzer(conn, op, hash_pw):
    for e in op.get("eintraege") or []:
        akt = 1 if e.get("aktiv", 1) else 0
        if e.get("id"):
            conn.execute("UPDATE users SET login=?, name=?, rolle=?, aktiv=? WHERE id=?",
                         (e["login"].strip(), e["name"].strip(), e["rolle"], akt, e["id"]))
            if e.get("passwort"):
                h, s = hash_pw(e["passwort"])
                conn.execute("UPDATE users SET pw_hash=?, pw_salt=?, muss_pw_aendern=1 WHERE id=?", (h, s, e["id"]))
            if not akt:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (e["id"],))
            if "email" in e and "email" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:  # R5-Z
                conn.execute("UPDATE users SET email=? WHERE id=?", ((e["email"] or "").strip() or None, e["id"]))
        else:
            h, s = hash_pw(e.get("passwort") or __import__("secrets").token_urlsafe(24))  # R28-G1: Windows-Benutzer ohne Startpasswort
            conn.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern,aktiv) VALUES(?,?,?,?,?,?,?)",
                         (e["login"].strip(), e["name"].strip(), e["rolle"], h, s,
                          0 if e.get("muss_pw_aendern") == 0 else 1, akt))
            if e.get("email") and "email" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:  # R5-Z
                conn.execute("UPDATE users SET email=? WHERE login=?", (e["email"].strip(), e["login"].strip()))
    _anw_windows_login(conn, op)  # R28-G1
    try:  # R5-Z: Namen geändert → Zuständig-Verknüpfungen neu (nur wenn Server-Module vorhanden)
        import zustaendig
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='opl_zustaendig'").fetchone():
            zustaendig.alle_neu(conn)
    except ImportError:
        pass


def _anw_windows_login(conn, op):  # R28-G1: Windows-Benutzer (leer = lokale Anmeldung)
    import domaene
    domaene.migration(conn)
    for e in op.get("eintraege") or []:
        if "windows_login" in e:
            conn.execute("UPDATE users SET windows_login=? WHERE login=? COLLATE NOCASE",
                         (domaene.windows_login_bereinigen(e["windows_login"]), e["login"].strip()))


def _anw_pms(conn, op, hash_pw):
    conn.execute("DELETE FROM projekt_pm WHERE projekt_id=?", (op["projekt_id"],))
    for i in dict.fromkeys(int(x) for x in op["pm_ids"]):
        conn.execute("INSERT INTO projekt_pm(projekt_id,user_id) VALUES(?,?)", (op["projekt_id"], i))


def _anw_eigentuemer(conn, op, hash_pw):
    conn.execute("UPDATE angebote SET eigentuemer_id=?, version=version+1 WHERE id=?",
                 (op["eigentuemer_id"], op["angebot_id"]))


def _anw_einst(conn, op, hash_pw):
    for k, v in (op.get("werte") or {}).items():
        conn.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", ("cfg." + k, str(v)))


def _anw_firma(conn, op, hash_pw):  # R26-F
    import firma
    for k, v in (op.get("werte") or {}).items():
        firma.set(conn, k, v)


_ANW = {"liste": _anw_liste, "benutzer": _anw_benutzer, "projekt_pms": _anw_pms,
        "angebot_eigentuemer": _anw_eigentuemer, "einstellungen": _anw_einst, "firma_setzen": _anw_firma,
        "ablage_global": _anw_ablage_global, "vertretungen": _anw_vertretungen}


# ---------------------------------------------------------------- Wiederherstellen
def wiederherstellen(conn, quelle):
    """Spielt die Sicherungsdatei `quelle` in die offene Verbindung `conn` ein (SQLite-Backup-API).

    Sitzungen bleiben erhalten (sonst wäre der Admin sofort abgemeldet), rev wird über
    den bisherigen Stand hinaus erhöht, damit alle Oberflächen neu laden.
    """
    alt_rev = int(conn.execute("SELECT v FROM meta WHERE k='rev'").fetchone()[0])
    sitzungen = conn.execute("SELECT token, user_id, erstellt, zuletzt FROM sessions").fetchall()
    # Geräte-Zeilen der erhaltenen Sitzungen mitnehmen (sonst liefe ein Geräte-Cookie ohne PIN-Schutz weiter)
    try:
        g_cols = [r[1] for r in conn.execute("PRAGMA table_info(geraete)")]
        geraete = conn.execute(f"SELECT {', '.join(g_cols)} FROM geraete").fetchall() if g_cols else []
    except sqlite3.Error:
        g_cols, geraete = [], []
    src = sqlite3.connect(f"file:{_uri_pfad(quelle)}?mode=ro", uri=True)
    try:
        src.backup(conn)
    finally:
        src.close()
    neu_rev = int(conn.execute("SELECT v FROM meta WHERE k='rev'").fetchone()[0])
    conn.execute("UPDATE meta SET v=? WHERE k='rev'", (str(max(alt_rev, neu_rev) + 1),))
    for s in sitzungen:
        if conn.execute("SELECT 1 FROM users WHERE id=?", (s[1],)).fetchone():
            conn.execute("INSERT OR IGNORE INTO sessions(token,user_id,erstellt,zuletzt) VALUES(?,?,?,?)", tuple(s))
    tok_i = g_cols.index("token") if "token" in g_cols else None
    neu_cols = {r[1] for r in conn.execute("PRAGMA table_info(geraete)")}
    if tok_i is not None and set(g_cols) <= neu_cols:
        for g in geraete:
            if conn.execute("SELECT 1 FROM sessions WHERE token=?", (g[tok_i],)).fetchone():
                conn.execute("DELETE FROM geraete WHERE token=?", (g[tok_i],))
                conn.execute(f"INSERT OR REPLACE INTO geraete({', '.join(g_cols)}) VALUES({', '.join('?' * len(g_cols))})", tuple(g))
    return max(alt_rev, neu_rev) + 1


def _uri_pfad(pfad):
    """Pfad → SQLite-URI-Pfad (auch UNC: \\\\NAS\\x → ////NAS/x)."""
    from urllib.parse import quote
    p = str(pfad).replace("\\", "/")
    if p.startswith("//"):
        p = "//" + p                    # file:////NAS/share/...
    elif len(p) > 1 and p[1] == ":":
        p = "/" + p                     # file:/C:/...
    return quote(p, safe="/:")


def kopieren_sicher(quelle, ziel):
    shutil.copy2(str(quelle), str(ziel))


# ---------------------------------------------------------------- Historie
def historie_dir(data_dir):
    from pathlib import Path
    d = Path(data_dir) / "admin" / "pakete"
    d.mkdir(parents=True, exist_ok=True)
    return d


def historie_speichern(data_dir, paket, sicherung, ergebnis, via):
    """Legt <data>/admin/pakete/<zeit>-<id>.json an und gibt den Pfad zurück."""
    eintrag = dict(paket)
    eintrag.update({"eingespielt": _jetzt(), "sicherung": str(sicherung) if sicherung else None,
                    "auswirkungen": ergebnis.get("auswirkungen"), "via": via, "rueckgaengig": None})
    name = f"{eintrag['eingespielt'].replace(':', '').replace('-', '')}-{str(paket.get('id'))[:8]}.json"
    pfad = historie_dir(data_dir) / name
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(eintrag, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(pfad)
    return pfad


def historie_liste(data_dir):
    out = []
    for p in sorted(historie_dir(data_dir).glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["_datei"] = p.name
            out.append(d)
        except (OSError, ValueError):
            pass
    return out


def historie_markieren(data_dir, datei, **felder):
    p = historie_dir(data_dir) / datei
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update(felder)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def letztes_rueckgaengig_moeglich(data_dir):
    """Letztes nicht rückgängig gemachtes Paket (dict mit _datei) oder None."""
    for d in historie_liste(data_dir):
        if not d.get("rueckgaengig"):
            return d
    return None


def sicherungen_liste(root):
    import datetime as _dt
    from pathlib import Path
    out = []
    for art in ("vor-aktion", "stuendlich", "taeglich"):
        for f in sorted((Path(root) / art).glob("opl-*.db"), reverse=True):
            st = f.stat()
            out.append({"art": art, "datei": f.name, "groesse": st.st_size,
                        "zeit": _dt.datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).isoformat()})
    return out

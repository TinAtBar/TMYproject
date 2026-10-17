"""Gemeinsame Abfragen, Serialisierung, Konfliktprüfung und Suchindex-Pflege."""
import datetime as _dt
import json

from util import ApiError, norm, today_iso, now_iso, week_end_iso, to_int

# ------------------------------------------------------------------ Stammdaten-Caches
def lookup(db, table):
    return {r["id"]: r for r in db.q(f"SELECT * FROM {table} ORDER BY pos, id")}


def user_names(db):
    return {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users")}


# ------------------------------------------------------------------ OPL
OPL_FELDER = ("titel", "beschreibung", "kategorie_id", "verantwortlich_id", "prioritaet_id", "frist",
              "status_id", "baugruppe_id", "bauteil_id", "sn_id")

OPL_BASE_SQL = """
SELECT o.*, p.nummer AS projekt_nummer, p.bezeichnung AS projekt_bezeichnung,
       b.nummer AS baugruppe_nummer, b.bezeichnung AS baugruppe_bezeichnung,
       bt.bezeichnung AS bauteil_bezeichnung, s.sn AS sn,
       uv.name AS verantwortlich_name, ue.name AS erstellt_von_name, ug.name AS geaendert_von_name,
       st.name AS st_name, st.farbe AS st_farbe, st.art AS st_art,
       pr.name AS pr_name, pr.farbe AS pr_farbe, pr.pos AS pr_pos,
       k.name AS k_name, k.farbe AS k_farbe,
       (SELECT COUNT(*) FROM kommentare WHERE opl_id=o.id) AS kommentare_anzahl,
       (SELECT COUNT(*) FROM dateien WHERE opl_id=o.id) AS dateien_anzahl,
       (SELECT GROUP_CONCAT(zu.id || ':' || zu.name, '|') FROM opl_zustaendig zl JOIN users zu ON zu.id=zl.user_id
        WHERE zl.opl_id=o.id) AS zust_links
FROM opl o
JOIN projekte p ON p.id=o.projekt_id
LEFT JOIN baugruppen b ON b.id=o.baugruppe_id
LEFT JOIN bauteile bt ON bt.id=o.bauteil_id
LEFT JOIN seriennummern s ON s.id=o.sn_id
LEFT JOIN users uv ON uv.id=o.verantwortlich_id
LEFT JOIN users ue ON ue.id=o.erstellt_von
LEFT JOIN users ug ON ug.id=o.geaendert_von
LEFT JOIN status_opl st ON st.id=o.status_id
LEFT JOIN prioritaeten pr ON pr.id=o.prioritaet_id
LEFT JOIN kategorien k ON k.id=o.kategorie_id
"""


def opl_item(r):
    """Wandelt eine Zeile aus OPL_BASE_SQL in das API-Item um."""
    d = dict(r)
    d["nr"] = d["id"]
    d["status"] = {"id": d["status_id"], "name": d.pop("st_name"), "farbe": d.pop("st_farbe"), "art": d.pop("st_art")}
    d["prioritaet"] = {"id": d["prioritaet_id"], "name": d.pop("pr_name"), "farbe": d.pop("pr_farbe"), "pos": d.pop("pr_pos")}
    kn, kf = d.pop("k_name"), d.pop("k_farbe")
    d["kategorie"] = {"id": d["kategorie_id"], "name": kn, "farbe": kf} if d["kategorie_id"] else None
    d["ueberfaellig"] = bool(d["frist"] and d["frist"] < today_iso() and d["status"]["art"] == "offen")
    d["erledigt"] = d["status"]["art"] == "abgeschlossen"
    zl = d.pop("zust_links", None)  # R5-Z: erkannte Benutzer im Feld „Zuständig“
    d["zustaendig_chips"] = sorted(({"user_id": int(x.split(":", 1)[0]), "name": x.split(":", 1)[1]}
                                    for x in (zl or "").split("|") if ":" in x), key=lambda c: c["name"])
    d["zustaendig_user_ids"] = [c["user_id"] for c in d["zustaendig_chips"]]
    return d


def opl_get(db_or_conn, oid, include_deleted=False):
    sql = OPL_BASE_SQL + " WHERE o.id=?" + ("" if include_deleted else " AND o.geloescht=0")
    if hasattr(db_or_conn, "q1"):
        r = db_or_conn.q1(sql, (oid,))
    else:
        r = db_or_conn.execute(sql, (oid,)).fetchone()
    if not r:
        raise ApiError(404, "Offener Punkt nicht gefunden")
    return opl_item(r)


SORTS = {"frist": "o.frist IS NULL, o.frist, o.id", "-frist": "o.frist IS NULL, o.frist DESC",
         "-geaendert_am": "o.geaendert_am DESC, o.id DESC", "geaendert_am": "o.geaendert_am",
         "nr": "o.id", "-nr": "o.id DESC", "prioritaet": "pr.pos, o.frist IS NULL, o.frist",
         "titel": "o.titel COLLATE NOCASE",
         "-titel": "o.titel COLLATE NOCASE DESC", "-prioritaet": "pr.pos DESC, o.frist IS NULL, o.frist",  # R4-T
         "status": "st.pos, o.id", "-status": "st.pos DESC, o.id"}  # R4-T


def opl_filter(ctx, extra_where=None):
    """Baut WHERE + Parameter aus Query-Parametern (/api/opl und Export)."""
    w, a = ["o.geloescht=0"], []
    # R5-Z: Zuständig-Benutzer über Verknüpfung opl_zustaendig – zustaendig_user_id (R5-L-UI), zustaendig_user,
    # Altparameter verantwortlich_id; Mehrfachwerte „1,2“, „null“ = niemand eingetragen
    for pn in ("zustaendig_user_id", "zustaendig_user", "verantwortlich_id"):
        v = ctx.qp(pn)
        if v in (None, ""):
            continue
        teile_zu, ids_zu = [], []
        for x in str(v).split(","):
            x = x.strip()
            if x in ("null", "none", "0"):
                teile_zu.append("TRIM(COALESCE(o.zustaendig_text,''))=''")
            elif x:
                ids_zu.append(to_int(x, pn))
        if ids_zu:
            teile_zu.append(f"EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id=o.id AND zz.user_id IN ({','.join('?' * len(ids_zu))}))")
            a += ids_zu
        if teile_zu:
            w.append("(" + " OR ".join(teile_zu) + ")")
    for k in ("projekt_id", "baugruppe_id", "status_id", "prioritaet_id", "kategorie_id", "sn_id"):  # R5-Z: ohne verantwortlich_id
        v = ctx.qp(k)
        if v not in (None, "") and "," in str(v):  # R5-L: Mehrfachwerte projekt_id=1,2,3 (auch „null“ = ohne)
            teile_mv, ids_mv = [], []
            for x in str(v).split(","):
                x = x.strip()
                if not x:
                    continue
                if x in ("null", "none", "0") and k in ("verantwortlich_id", "kategorie_id", "baugruppe_id"):
                    teile_mv.append(f"o.{k} IS NULL")
                else:
                    ids_mv.append(to_int(x, k))
            if ids_mv:
                teile_mv.append(f"o.{k} IN ({','.join('?' * len(ids_mv))})")
                a += ids_mv
            if teile_mv:
                w.append("(" + " OR ".join(teile_mv) + ")")
        elif v not in (None, ""):
            if v in ("null", "none", "0") and k in ("verantwortlich_id", "kategorie_id", "baugruppe_id"):
                w.append(f"o.{k} IS NULL")
            else:
                w.append(f"o.{k}=?")
                a.append(to_int(v, k))
    # R5-L-Filter zustaendig_user_id: von R5-Z oben über die Verknüpfungstabelle umgesetzt
    art = ctx.qp("status_art", "offen")
    if art in ("offen", "abgeschlossen"):
        w.append("st.art=?")
        a.append(art)
    if ctx.qp("ueberfaellig") in ("1", "true"):
        w.append("o.frist < ? AND st.art='offen'")
        a.append(today_iso())
    if ctx.qp("woche") in ("1", "true"):
        w.append("o.frist BETWEEN ? AND ? AND st.art='offen'")
        a += [today_iso(), week_end_iso()]
    if ctx.qp("frist_bis"):
        w.append("o.frist <= ?")
        a.append(ctx.qp("frist_bis"))
    q = (ctx.qp("q") or "").strip()
    if q:
        for term in q.split():
            like = f"%{term}%"
            w.append("(o.titel LIKE ? OR o.beschreibung LIKE ? OR p.nummer LIKE ? OR b.nummer LIKE ? OR s.sn LIKE ?"
                     " OR CAST(o.id AS TEXT)=? OR o.zustaendig_text LIKE ?)")  # R3-B: + zustaendig_text
            a += [like, like, like, like, like, term, like]
    if ctx.qp("archiv") not in ("1", "true", "alle") and ctx.qp("projekt_id") in (None, ""):  # R3-A: Archiv ausblenden
        w.append("COALESCE(p.archiviert,0)=0")  # R3-A:
    mw = meine_where(ctx)  # R4-T: „Nur meine“
    if mw:
        w.append(mw[0])
        a += mw[1]
    if extra_where:
        w.append(extra_where[0])
        a += extra_where[1]
    order = ", ".join(SORTS[x] for x in (ctx.qp("sort") or "frist").split(",") if x in SORTS) or SORTS["frist"]  # R5-L: Sekundärsortierung „a,b“
    return " WHERE " + " AND ".join(w), a, order


def meine_where(ctx, alias="o"):
    """R4-T: ?meine=1 – PM: Punkte in meinen Projekten ODER mir zugewiesen ODER mein Name in „Zuständig“;
    Mitarbeiter/Admin: mir zugewiesen ODER mein Name in „Zuständig“."""
    if ctx.qp("meine") not in ("1", "true") or not ctx.user:
        return None
    u = ctx.user
    teile = [f"EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id={alias}.id AND zz.user_id=?)"]  # R5-Z
    args = [u["id"]]
    if u["rolle"] == "pm":
        teile.append(f"{alias}.projekt_id IN (SELECT projekt_id FROM projekt_pm WHERE user_id=?)")
        args.append(u["id"])
    return "(" + " OR ".join(teile) + ")", args


# R4-T: Spaltenschlüssel der OPL-Exporte (Reihenfolge = Standard)
EXPORT_SPALTEN = ("nr", "projekt", "baugruppe", "sn", "titel", "beschreibung", "kategorie",
                  "prioritaet", "frist", "status", "ueberfaellig", "erstellt_von", "erstellt_am", "geaendert_am",
                  "erledigt_am", "zustaendig")


def export_indizes(ctx, extra=()):
    """R4-T: ?spalten=nr,titel,… → Liste der Spaltenindizes in gewünschter Reihenfolge (None = alle).
    R26-H: extra = zusätzliche Schlüssel (z. B. Zusatzfelder „z:key“), angehängt hinter EXPORT_SPALTEN."""
    alle = list(EXPORT_SPALTEN) + list(extra)
    sp = (ctx.qp("spalten") or "").strip()
    if not sp:
        return None
    out = []
    for k in sp.split(","):
        k = k.strip()
        if k in alle and alle.index(k) not in out:
            out.append(alle.index(k))
    return out or None


# ------------------------------------------------------------------ Konfliktprüfung
def apply_changes(conn, table, row, changes, base, allowed, von=None, am=None, item_fn=None):
    """Feldweise Konfliktprüfung. Gibt dict der wirklich geänderten Felder {feld: (alt, neu)}.

    Regel: aktueller Wert == base → übernehmen; aktueller Wert == neuer Wert → ok; sonst Konflikt.
    Fehlt ein Feld in base, wird ohne Prüfung übernommen.
    """
    base = base or {}
    konflikt, geaendert = [], {}
    for f, neu in changes.items():
        if f not in allowed:
            raise ApiError(400, f"Feld „{f}“ kann nicht geändert werden")
        cur = row[f]
        if f in base and norm(cur) != norm(base[f]) and norm(cur) != norm(neu):
            konflikt.append(f)
        elif norm(cur) != norm(neu):
            geaendert[f] = (cur, neu)
    if konflikt:
        item = item_fn() if item_fn else dict(row)
        raise ApiError(409, "Konflikt", felder=konflikt, item=item, von=von, am=am)
    return geaendert


def letzte_aenderung(conn, objekt, oid):
    r = conn.execute("SELECT a.zeit, u.name FROM activity a LEFT JOIN users u ON u.id=a.user_id "
                     "WHERE a.objekt=? AND a.objekt_id=? ORDER BY a.id DESC LIMIT 1", (objekt, oid)).fetchone()
    return (r[1], r[0]) if r else (None, None)


# ------------------------------------------------------------------ Suchindex
def idx_opl(db, conn, oid, notify=True):
    import zustaendig; zustaendig.pflegen(conn, oid, notify)  # R5-Z: Verknüpfungen + Benachrichtigung
    r = conn.execute("SELECT o.*, p.nummer pn, b.nummer bn, s.sn FROM opl o JOIN projekte p ON p.id=o.projekt_id "
                     "LEFT JOIN baugruppen b ON b.id=o.baugruppe_id LEFT JOIN seriennummern s ON s.id=o.sn_id "
                     "WHERE o.id=?", (oid,)).fetchone()
    if not r or r["geloescht"]:
        db.unindex(conn, "opl", oid)
        return
    db.index(conn, "opl", oid, r["projekt_id"], r["titel"],
             " ".join(x for x in (r["beschreibung"], r["pn"], r["bn"], r["sn"],
                                  r["zustaendig_text"] if "zustaendig_text" in r.keys() else None) if x))  # R3-B


def idx_projekt(db, conn, pid):
    r = conn.execute("SELECT * FROM projekte WHERE id=?", (pid,)).fetchone()
    if not r:
        db.unindex(conn, "projekt", pid)
        return
    db.index(conn, "projekt", pid, pid, f"{r['nummer']} {r['bezeichnung'] or ''}",
             " ".join(x for x in (r["kunde"], r["ort"]) if x))


def idx_baugruppe(db, conn, bid):
    r = conn.execute("SELECT * FROM baugruppen WHERE id=?", (bid,)).fetchone()
    if not r:
        db.unindex(conn, "baugruppe", bid)
        return
    sns = [x[0] for x in conn.execute("SELECT sn FROM seriennummern WHERE baugruppe_id=?", (bid,))]
    teile = [f"{x[0] or ''} {x[1] or ''}" for x in conn.execute("SELECT bezeichnung, zeichnung FROM bauteile WHERE baugruppe_id=?", (bid,))]
    db.index(conn, "baugruppe", bid, r["projekt_id"], f"{r['nummer']} {r['bezeichnung'] or ''}", " ".join(sns + teile))


def idx_angebot(db, conn, aid):
    r = conn.execute("SELECT * FROM angebote WHERE id=?", (aid,)).fetchone()
    if not r or r["geloescht"]:
        db.unindex(conn, "angebot", aid)
        return
    db.index(conn, "angebot", aid, r["projekt_id"], f"{r['nummer'] or ''} {r['bezeichnung'] or ''}", r["kunde"] or "")


def idx_kommentar(db, conn, kid):
    r = conn.execute("SELECT k.*, o.projekt_id, a.projekt_id apid FROM kommentare k LEFT JOIN opl o ON o.id=k.opl_id "
                     "LEFT JOIN angebote a ON a.id=k.angebot_id WHERE k.id=?", (kid,)).fetchone()
    if not r:
        db.unindex(conn, "kommentar", kid)
        return
    db.index(conn, "kommentar", kid, r["projekt_id"] or r["apid"], "Kommentar", r["text"])


def idx_datei(db, conn, did):
    r = conn.execute("SELECT * FROM dateien WHERE id=?", (did,)).fetchone()
    if not r:
        db.unindex(conn, "datei", did)
        return
    db.index(conn, "datei", did, r["projekt_id"], r["name"], "")


def reindex_all(db, conn):
    conn.execute("DELETE FROM suche")
    for t, fn in (("opl", lambda d, c, i: idx_opl(d, c, i, notify=False)), ("projekte", idx_projekt), ("baugruppen", idx_baugruppe),  # R5-Z: ohne Benachrichtigung
                  ("angebote", idx_angebot), ("kommentare", idx_kommentar), ("dateien", idx_datei)):
        for (i,) in conn.execute(f"SELECT id FROM {t}").fetchall():
            fn(db, conn, i)


def projekt_or_404(db, pid):
    p = db.q1("SELECT * FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    return p


def activity_rows(db, where, args, limit=50):
    rows = db.q("SELECT a.*, u.name AS user_name, p.nummer AS projekt_nummer FROM activity a "
                "LEFT JOIN users u ON u.id=a.user_id LEFT JOIN projekte p ON p.id=a.projekt_id "
                f"WHERE {where} ORDER BY a.id DESC LIMIT {int(limit)}", args)
    for r in rows:
        try:
            r["details"] = json.loads(r["details"] or "{}")
        except ValueError:
            r["details"] = {}
        r["titel"] = r["details"].get("titel")
        if r["details"].get("als_vertretung"):  # R27-105
            r["user_name"] = f"{r['user_name'] or '?'} (als Vertretung für {r['details']['als_vertretung']})"
        if r["details"].get("antrag"):  # R27-104
            r["user_name"] = f"{r['user_name'] or '?'} – {r['details']['antrag']}"
    return rows

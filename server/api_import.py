"""Excel-Import: Vorkalkulations-Mappen (kalkulation.py) und flexibler Parser per Spaltenüberschrift."""
import re

from router import route
from util import ApiError, to_int, dumps
import multipart
import kalkulation
import nummern
import xlsx

NR_KEYS = ("nr", "nr.", "pos", "pos.", "position", "nummer", "auftragsnummer", "baugruppe")
BEZ_KEYS = ("bezeichnung", "benennung", "beschreibung", "text")
MENGE_KEYS = ("menge", "anzahl", "stk", "stück", "stk.")


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def analysiere(rows, kat_namen):
    warnungen = []
    kopf_i, kopf = None, None
    for i, r in enumerate(rows[:30]):
        cells = [_norm(c) for c in r]
        if any(c in BEZ_KEYS for c in cells):
            kopf_i, kopf = i, cells
            break
    erkannt = {"nummer": None, "ist_angebot": False, "bezeichnung": None}
    # Kopfnummer irgendwo oberhalb suchen
    for r in rows[: (kopf_i if kopf_i is not None else 10) + 1]:
        for c in r:
            m = re.search(r"\b([0-9A-Za-z]{4}-[0-9A-Za-z]{3}-\d{2})\b", str(c or ""))
            if m and not erkannt["nummer"]:
                erkannt["nummer"] = nummern.hauptnummer(m.group(1))
    if erkannt["nummer"]:
        erkannt["ist_angebot"] = nummern.ist_angebot(erkannt["nummer"])
    if kopf is None:
        warnungen.append("Keine Überschriftenzeile mit „Bezeichnung“ gefunden")
        return erkannt, [], warnungen
    # Bezeichnung des Projekts: Zelle rechts neben "Projekt"/"Bezeichnung" oberhalb des Kopfs
    for r in rows[:kopf_i]:
        for j, c in enumerate(r[:-1]):
            if _norm(c) in ("projekt", "projektbezeichnung", "bezeichnung", "objekt") and r[j + 1]:
                erkannt["bezeichnung"] = str(r[j + 1])
    def col(keys):
        for j, c in enumerate(kopf):
            if c in keys:
                return j
        return None
    c_nr, c_bez, c_menge = col(NR_KEYS), col(BEZ_KEYS), col(MENGE_KEYS)
    kat_cols = {}
    for j, c in enumerate(kopf):
        for k in kat_namen:
            if c == k.lower() or c.startswith(k.lower() + " "):
                kat_cols[j] = k
    if not kat_cols:
        warnungen.append("Keine Budget-Spalten erkannt")
    bgs = []
    for zi, r in enumerate(rows[kopf_i + 1:], start=kopf_i + 2):
        get = lambda j: r[j] if j is not None and j < len(r) else None
        bez = get(c_bez)
        if bez in (None, ""):
            continue
        nr = str(get(c_nr) or "").strip() or None
        if nr and re.fullmatch(r"\d{1,2}", nr) and erkannt["nummer"]:
            nr = f"{erkannt['nummer'][:8]}-{int(nr):02d}"
        if nr and not nummern.ALLG_RE.match(nr):
            warnungen.append(f"Zeile {zi}: Nummer „{nr}“ nicht im Format XXXX-XXX-NN, wird neu vergeben")
            nr = None
        try:
            menge = int(float(get(c_menge) or 1))
        except (TypeError, ValueError):
            warnungen.append(f"Zeile {zi}: Menge „{get(c_menge)}“ ungültig, 1 angenommen")
            menge = 1
        budgets = {}
        for j, k in kat_cols.items():
            v = get(j)
            if v not in (None, ""):
                try:
                    budgets[k] = float(str(v).replace(",", "."))
                except ValueError:
                    warnungen.append(f"Zeile {zi}: Wert „{v}“ in {k} ist keine Zahl")
        bgs.append({"nummer": nr, "bezeichnung": str(bez), "menge": menge, "budgets": budgets})
    if not bgs:
        warnungen.append("Keine Positionen gefunden")
    return erkannt, bgs, warnungen


@route("POST", "/api/import/excel/vorschau", raw=True)
def vorschau(ctx):
    ctx.r.need_pm_or_admin()
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    f = files.get("datei") or (next(iter(files.values())) if files else None)
    if not f:
        raise ApiError(400, "Keine Datei hochgeladen (Feld „datei“)")
    try:
        analyse = kalkulation.lesen(f[2])
        if analyse is None:
            rows = xlsx.lesen(f[2])
    except (ValueError, KeyError, IndexError) as e:
        raise ApiError(400, f"Excel-Datei konnte nicht gelesen werden: {e}")
    except Exception as e:  # z. B. kaputtes XML
        raise ApiError(400, f"Excel-Datei konnte nicht gelesen werden: {type(e).__name__}")
    if analyse is not None:
        with ctx.db.lock:
            kalkulation.abgleich(ctx.db.conn, analyse)
        return _kalk_antwort(analyse, f[0])
    kats = [r["name"] for r in ctx.db.q("SELECT name FROM budget_kategorien")]
    erkannt, bgs, warn = analysiere(rows, kats)
    return {"art": "tabelle", "erkannt": erkannt, "baugruppen": bgs, "warnungen": warn, "dateiname": f[0]}


def _kalk_antwort(a, dateiname):
    k, z = a["kopf"], a["ziel"]
    warn = list(a["warnungen"])
    for p in a["positionen"]:
        warn.extend(p["warnungen"])
    bgs = [{"nummer": p["nummer"], "bezeichnung": p["bezeichnung"], "menge": p["anzahl"], "budgets": p["budgets"],
            "blatt": p["blatt"], "index": p["index"], "item": p["item"], "bezeichnung_roh": p["bezeichnung_roh"],
            "genius_nr": p["genius_nr"], "gewicht_t": p["gewicht_t"], "stunden": p["stunden"],
            "schweissverfahren": p["schweissverfahren"], "stunden_gesamt": p["stunden_gesamt"],
            "stunden_soll": p["stunden_soll"], "ohne_stunden": p["ohne_stunden"], "status": p["status"],
            "alt": p["alt"], "warnungen": p["warnungen"]} for p in a["positionen"]]
    return {"art": "kalkulation", "kopf": k, "ziel": z,
            "erkannt": {"nummer": z["nummer"], "ist_angebot": z["typ"] == "angebot",
                        "bezeichnung": k.get("projektbezeichnung") or k.get("objekt"), "kunde": k.get("kunde")},
            "baugruppen": bgs, "summe_stunden": a["summe_stunden"], "warnungen": warn, "dateiname": dateiname}


def _budgets_setzen(c, bid, budgets, ersetzen):
    """Setzt Stunden je Kategorie (Beträge bleiben). ersetzen: vorher importierte Kategorien ohne Wert → 0."""
    ids = {}
    for k, std in (budgets or {}).items():
        kid = kalkulation.kategorie_id(c, str(k))
        if kid:
            ids[kid] = float(std or 0)
    if ersetzen:
        for (kid,) in c.execute("SELECT kategorie_id FROM budgets WHERE baugruppe_id=? AND COALESCE(stunden,0)<>0", (bid,)).fetchall():
            ids.setdefault(kid, 0.0)
    for kid, std in ids.items():
        c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(?,?,?) "
                  "ON CONFLICT(baugruppe_id,kategorie_id) DO UPDATE SET stunden=excluded.stunden", (bid, kid, std))


def _kalk_uebernehmen(ctx, v, ziel):
    """Kalkulationsmappe → Auftrag (mit Auftrags-Nr.) bzw. Angebot (nur Angebots-Nr.)."""
    from api_projekte import projekt_anlegen, baugruppe_anlegen, sn_ergaenzen
    from common import idx_baugruppe, idx_projekt
    kopf = v.get("kopf") or {}
    bgs = [b for b in (v.get("baugruppen") or []) if b.get("uebernehmen", True)]
    auftrag = (kopf.get("auftrags_nr") or "").strip()
    typ = ziel.get("typ") or ("auftrag" if auftrag else "angebot")
    bez = ziel.get("bezeichnung") or kopf.get("projektbezeichnung") or kopf.get("objekt") or "Import"
    kunde = ziel.get("kunde") or kopf.get("kunde")
    if typ in ("auftrag", "neu", "bestehend"):
        if not auftrag:
            raise ApiError(400, "Die Kalkulation enthält keine Auftrags-Nr. – bitte als Angebot importieren")
        nummern.pruefe_auftrag(auftrag, haupt=True)
        p = ctx.db.q1("SELECT id FROM projekte WHERE nummer=?", (auftrag,))
        if p:
            ctx.r.need_projekt(p["id"])
    # R3-B: Ziel {typ:'nachtrag', projekt_id} → Angebot als Nachtrag zum Projekt
    nachtrag_pid = None
    if typ == "nachtrag":
        nachtrag_pid = to_int(ziel.get("projekt_id"), "projekt_id", allow_none=False)
        if not ctx.db.q1("SELECT 1 FROM projekte WHERE id=?", (nachtrag_pid,)):
            raise ApiError(404, "Projekt nicht gefunden")
        ctx.r.need_projekt(nachtrag_pid)
    ctx.app.backup.vor_aktion("import")

    def fn(c):
        kalkulation.migration(c)
        if typ in ("angebot", "nachtrag"):  # R3-B: + nachtrag
            nr = (kopf.get("angebots_nr") or ziel.get("nummer") or "").strip()
            nummern.pruefe_allg(nr, haupt=True)
            a = c.execute("SELECT id FROM angebote WHERE nummer=? AND COALESCE(geloescht,0)=0", (nr,)).fetchone()
            if a:
                aid = a[0]
                c.execute("DELETE FROM angebot_positionen WHERE angebot_id=?", (aid,))
                c.execute("UPDATE angebote SET kunde=COALESCE(kunde,?), bezeichnung=COALESCE(bezeichnung,?), version=version+1 WHERE id=?",
                          (kunde, bez, aid))
                aktion = "geaendert"
                if nachtrag_pid:  # R3-B
                    c.execute("UPDATE angebote SET art='nachtrag', projekt_id=? WHERE id=?", (nachtrag_pid, aid))
            else:
                st = c.execute("SELECT id FROM status_angebot ORDER BY pos LIMIT 1").fetchone()[0]
                aid = c.execute("INSERT INTO angebote(nummer,art,bezeichnung,kunde,eigentuemer_id,status_id) VALUES(?,?,?,?,?,?)",
                                (nr, "nachtrag" if nachtrag_pid else "angebot", bez, kunde, ctx.user["id"], st)).lastrowid
                if nachtrag_pid:  # R3-B
                    c.execute("UPDATE angebote SET projekt_id=? WHERE id=?", (nachtrag_pid, aid))
                aktion = "angelegt"
            for i, b in enumerate(bgs):
                for k in (b.get("budgets") or {}):
                    kalkulation.kategorie_id(c, str(k))  # damit die Umwandlung die Kategorien findet
                c.execute("INSERT INTO angebot_positionen(angebot_id,nummer,bezeichnung,menge,budgets,pos) VALUES(?,?,?,?,?,?)",
                          (aid, f"{nr} {b.get('blatt') or i + 1}", b.get("bezeichnung"), max(to_int(b.get("menge")) or 0, 1),
                           dumps(b.get("budgets") or {}), i))
            from common import idx_angebot
            idx_angebot(ctx.db, c, aid)
            ctx.db.activity(c, ctx.user, "angebot", aid, nachtrag_pid, aktion, {"titel": nr, "import": True, "positionen": len(bgs)})
            return {"angebot_id": aid, "positionen": len(bgs), "art": "nachtrag" if nachtrag_pid else "angebot"}  # R3-B: art

        p = c.execute("SELECT id, angebot_ref, kunde, bezeichnung FROM projekte WHERE nummer=?", (auftrag,)).fetchone()
        qip_neu = False  # R4-P
        if p:
            pid = p[0]
            c.execute("UPDATE projekte SET angebot_ref=COALESCE(NULLIF(angebot_ref,''),?), kunde=COALESCE(NULLIF(kunde,''),?), "
                      "bezeichnung=COALESCE(NULLIF(bezeichnung,''),?) WHERE id=?", (kopf.get("angebots_nr"), kunde, bez, pid))
            idx_projekt(ctx.db, c, pid)
        else:
            pid = projekt_anlegen(ctx, c, auftrag, bez, kunde, ziel.get("ort"), ziel.get("pm_ids") or [ctx.user["id"]],
                                  angebot_ref=kopf.get("angebots_nr"))
            qip_neu = True  # R4-P: QIP erst nach den Baugruppen
        neu = akt = 0
        for b in bgs:
            k = to_int(b.get("index"), "index") or 0
            if k < 1 or k > 99:
                raise ApiError(400, f"Ungültige Positionsnummer {b.get('index')}")
            nr = kalkulation.bg_nummer(auftrag, k)
            menge = max(to_int(b.get("menge")) or 0, 1)
            row = c.execute("SELECT id, projekt_id, menge, bezeichnung FROM baugruppen WHERE nummer=?", (nr,)).fetchone()
            if row and row[1] != pid:
                raise ApiError(409, f"Baugruppennummer {nr} gehört zu einem anderen Projekt")
            if row:
                bid = row[0]
                neue_menge = max(row[2] or 0, menge)  # nie verringern, keine Neu-Nummerierung
                c.execute("UPDATE baugruppen SET bezeichnung=?, menge=?, genius_nr=?, gewicht_t=?, version=version+1 WHERE id=?",
                          (b.get("bezeichnung"), neue_menge, b.get("genius_nr"), b.get("gewicht_t"), bid))
                sn_ergaenzen(c, bid)
                ctx.db.activity(c, ctx.user, "baugruppe", bid, pid, "geaendert",
                                {"titel": nr, "import": True, "felder": {"menge": [row[2], neue_menge], "bezeichnung": [row[3], b.get("bezeichnung")]}})
                idx_baugruppe(ctx.db, c, bid)
                akt += 1
            else:
                bid = baugruppe_anlegen(ctx, c, pid, nr, b.get("bezeichnung"), menge,
                                        angebot_ref=kopf.get("angebots_nr"))
                c.execute("UPDATE baugruppen SET genius_nr=?, gewicht_t=? WHERE id=?", (b.get("genius_nr"), b.get("gewicht_t"), bid))
                neu += 1
            _budgets_setzen(c, bid, b.get("budgets"), ersetzen=bool(row))
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert",
                        {"titel": auftrag, "import": True, "revision": kopf.get("revision"), "neu": neu, "aktualisiert": akt})
        qip_n = __import__("qip").option_anwenden(ctx, c, pid, _qip_vid(ctx, ziel)) if qip_neu else 0  # R4-P
        return {"projekt_id": pid, "neu": neu, "aktualisiert": akt, "qip_schritte": qip_n}
    return ctx.db.write(ctx.user, "import", fn, ctx.body.get("change_id"), ctx.body)


def _qip_vid(ctx, ziel):
    """R4-P: qip_vorlage_id aus ziel oder Body (nur wirksam, wenn ein neues Projekt entsteht)."""
    return ziel.get("qip_vorlage_id") or ctx.body.get("qip_vorlage_id")


@route("POST", "/api/import/excel/uebernehmen")
def uebernehmen(ctx):
    """Body: {vorschau:{erkannt, baugruppen[]}, ziel:{typ:'neu'|'bestehend'|'angebot', projekt_id?, nummer?, bezeichnung?, kunde?, pm_ids?}}"""
    ctx.r.need_pm_or_admin()
    v = ctx.body.get("vorschau") or {}
    ziel = ctx.body.get("ziel") or {}
    if isinstance(ziel, str):
        ziel = {"typ": ziel}
    if v.get("art") == "kalkulation":
        return _kalk_uebernehmen(ctx, v, ziel)
    typ = ziel.get("typ") or ("angebot" if (v.get("erkannt") or {}).get("ist_angebot") else "neu")
    bgs = v.get("baugruppen") or []
    if typ == "bestehend":
        ctx.r.need_projekt(to_int(ziel.get("projekt_id"), "projekt_id", allow_none=False))
    ctx.app.backup.vor_aktion("import")
    from api_projekte import projekt_anlegen, baugruppe_anlegen
    erkannt = v.get("erkannt") or {}

    def fn(c):
        if typ == "angebot":
            nr = ziel.get("nummer") or erkannt.get("nummer")
            nummern.pruefe_allg(nr or "", haupt=True)
            st = c.execute("SELECT id FROM status_angebot ORDER BY pos LIMIT 1").fetchone()[0]
            aid = c.execute("INSERT INTO angebote(nummer,art,bezeichnung,kunde,eigentuemer_id,status_id) VALUES(?,?,?,?,?,?)",
                            (nr, "angebot", ziel.get("bezeichnung") or erkannt.get("bezeichnung"), ziel.get("kunde"),
                             ctx.user["id"], st)).lastrowid
            for i, b in enumerate(bgs):
                c.execute("INSERT INTO angebot_positionen(angebot_id,nummer,bezeichnung,menge,budgets,pos) VALUES(?,?,?,?,?,?)",
                          (aid, b.get("nummer"), b.get("bezeichnung"), to_int(b.get("menge")) or 1, dumps(b.get("budgets") or {}), i))
            from common import idx_angebot
            idx_angebot(ctx.db, c, aid)
            ctx.db.activity(c, ctx.user, "angebot", aid, None, "angelegt", {"titel": nr, "import": True})
            return {"angebot_id": aid}
        if typ == "neu":
            pm_ids = ziel.get("pm_ids") or [ctx.user["id"]]
            pid = projekt_anlegen(ctx, c, ziel.get("nummer") or erkannt.get("nummer"),
                                  ziel.get("bezeichnung") or erkannt.get("bezeichnung") or "Import", ziel.get("kunde"), ziel.get("ort"), pm_ids)
            qip_vid = _qip_vid(ctx, ziel)  # R4-P
        elif typ == "bestehend":
            qip_vid = None  # R4-P
            pid = int(ziel["projekt_id"])
        else:
            raise ApiError(400, "Ungültiges Ziel")
        pnr = c.execute("SELECT nummer FROM projekte WHERE id=?", (pid,)).fetchone()[0]
        kats = {r[1].lower(): r[0] for r in c.execute("SELECT id, name FROM budget_kategorien")}
        for b in bgs:
            nr = b.get("nummer")
            if nr and (nummern.hauptnummer(nr) != pnr or c.execute("SELECT 1 FROM baugruppen WHERE nummer=?", (nr,)).fetchone()):
                nr = None
            bid = baugruppe_anlegen(ctx, c, pid, nr, b.get("bezeichnung"), b.get("menge") or 1)
            for k, std in (b.get("budgets") or {}).items():
                kid = kats.get(str(k).lower())
                if kid:
                    c.execute("INSERT OR REPLACE INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(?,?,?)", (bid, kid, float(std or 0)))
        return {"projekt_id": pid, "qip_schritte": __import__("qip").option_anwenden(ctx, c, pid, qip_vid)}  # R4-P
    return ctx.db.write(ctx.user, "import", fn, ctx.body.get("change_id"), ctx.body)

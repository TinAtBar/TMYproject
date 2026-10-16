"""R26-E: Fertigungsbesprechung verteilen.

Nach der Besprechung: Excel im bekannten Protokollformat (fertigung.export_mappe) erzeugen, mit Passwort
verschlüsseln (office_crypto, ECMA-376 Agile, AES-256/SHA-512), im Ablageverzeichnis speichern und einen
Mail-Entwurf (.eml, X-Unsent: 1) mit der verschlüsselten Datei als Anhang liefern. Das Passwort steht NIE in der Mail.

Firmeneinstellungen (firma_einstellungen, gepflegt in der Admin-Konsole, siehe docs/admin-seiten/fertigung.md):
  fertigung_verteilen_passwort    str   ""   (Pflicht)
  fertigung_verteilen_verzeichnis str   ""   (leer → <Datenordner>/Fertigungsbesprechung)
  fertigung_verteilen_dateiname   str   "Fertigungsbesprechung {datum}.xlsx"
  fertigung_verteilen_verteiler   list  []   (E-Mail-Adressen)
  fertigung_verteilen_betreff     str   "Fertigungsbesprechung {datum}"
  fertigung_verteilen_text        str   TEXT_DEFAULT  (Platzhalter {datum}, {datei}, {absender})
Rechte: Admin, Projektleiter, Controlling (Bereich fertigung = bearbeiten, Mitarbeiter nie).
"""
import datetime as _dt
import re
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.utils import formatdate, make_msgid
from pathlib import Path

import firma
import office_crypto
import rechte
from router import route
from util import ApiError, today_iso

K = "fertigung_verteilen_"
TEXT_DEFAULT = ("Hallo zusammen,\n\nanbei das Protokoll der Fertigungsbesprechung vom {datum} ({datei}).\n"
                "Die Datei ist passwortgeschützt – das Passwort erhaltet ihr wie gewohnt separat.\n\n"
                "Viele Grüße\n{absender}")
DEFAULTS = {"passwort": "", "verzeichnis": "", "dateiname": "Fertigungsbesprechung {datum}.xlsx", "verteiler": [],
            "betreff": "Fertigungsbesprechung {datum}", "text": TEXT_DEFAULT}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def einstellungen(conn):
    e = {k: firma.get(conn, K + k, v) for k, v in DEFAULTS.items()}
    v = e["verteiler"]
    if isinstance(v, str):
        v = re.split(r"[;,\s]+", v)
    e["verteiler"] = [x.strip() for x in (v or []) if isinstance(x, str) and "@" in x]
    return e


def verzeichnis(db, e=None):
    e = e or einstellungen(db.conn)
    return Path(e["verzeichnis"]) if (e["verzeichnis"] or "").strip() else Path(db.data_dir) / "Fertigungsbesprechung"


def _datum_de(iso):
    return _dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")


def _fuellen(muster, **w):
    out = str(muster or "")
    for k, v in w.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def dateiname(muster, stand):
    n = _fuellen(muster or DEFAULTS["dateiname"], datum=stand[:10], datum_de=_datum_de(stand))
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", n).strip(" .") or f"Fertigungsbesprechung {stand[:10]}"
    if not n.lower().endswith(".xlsx"):
        n += ".xlsx"
    return n


def _need(ctx):
    if ctx.user["rolle"] not in ("admin", "pm", "controlling") or not rechte.darf(ctx.user, "fertigung", "bearbeiten", ctx.db):
        raise ApiError(403, "Keine Berechtigung: Verteilen nur für Admin, Projektleiter oder Controlling")


def _absender(ctx):
    return ctx.user.get("name") or ctx.user.get("login") or ""


def eml(e, stand, name, data, absender):
    msg = MIMEMultipart("mixed")
    datum = _datum_de(stand)
    msg["Subject"] = Header(_fuellen(e["betreff"] or DEFAULTS["betreff"], datum=datum, datei=name), "utf-8")
    if e["verteiler"]:
        msg["To"] = ", ".join(e["verteiler"])
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid("fertigung")
    msg["X-Unsent"] = "1"
    text = _fuellen(e["text"] or TEXT_DEFAULT, datum=datum, datei=name, absender=absender)
    if e["passwort"] and e["passwort"] in text:  # Passwort nie in der Mail
        text = text.replace(e["passwort"], "********")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    part = MIMEBase(*XLSX_MIME.split("/"))
    part.set_payload(data)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
    msg.attach(part)
    return msg.as_bytes()


def verteilen(db, stand=None, erledigte=False, spin=office_crypto.SPIN):
    """Erzeugt + verschlüsselt + legt ab. → (Einstellungen, Pfad, Name, verschlüsselte Bytes)."""
    import fertigung
    e = einstellungen(db.conn)
    if not e["passwort"]:
        raise ApiError(400, "Kein Passwort für die Verteilung hinterlegt (Admin-Konsole → Fertigungsbesprechung)")
    stand = (stand or today_iso())[:10]
    klar = fertigung.export_mappe(db, stand, erledigte)
    enc = office_crypto.encrypt(klar, e["passwort"], spin)
    ziel = verzeichnis(db, e)
    try:
        ziel.mkdir(parents=True, exist_ok=True)
        name = dateiname(e["dateiname"], stand)
        pfad = ziel / name
        tmp = pfad.with_name(pfad.name + ".tmp")
        tmp.write_bytes(enc)
        tmp.replace(pfad)
    except OSError as ex:
        raise ApiError(500, f"Ablage nicht möglich ({ziel}): {ex.strerror or ex}")
    return e, pfad, name, enc


def _stand(ctx, v):
    v = (v or today_iso())[:10]
    try:
        _dt.date.fromisoformat(v)
    except ValueError:
        raise ApiError(400, "Ungültiges Stand-Datum")
    return v


@route("GET", "/api/fertigung/verteilen")
def info(ctx):
    """Einstellungen für die Oberfläche (ohne Passwort)."""
    _need(ctx)
    e = einstellungen(ctx.db.conn)
    return {"passwort_gesetzt": bool(e["passwort"]), "verzeichnis": str(verzeichnis(ctx.db, e)),
            "dateiname": dateiname(e["dateiname"], today_iso()), "verteiler": e["verteiler"]}


@route("POST", "/api/fertigung/verteilen")
def verteilen_api(ctx):
    """Body {stand?, erledigte?} → Datei abgelegt; {datei, pfad, verteiler, eml_url}."""
    _need(ctx)
    from fertigung import sicherstellen
    sicherstellen(ctx.db, ctx.user)
    stand = _stand(ctx, ctx.body.get("stand"))
    e, pfad, name, _ = verteilen(ctx.db, stand, bool(ctx.body.get("erledigte")))
    from urllib.parse import quote
    return {"ok": True, "datei": name, "pfad": str(pfad), "verteiler": e["verteiler"], "stand": stand,
            "eml_url": f"/api/fertigung/verteilen/entwurf.eml?datei={quote(name)}&stand={stand}"}


@route("GET", "/api/fertigung/verteilen/entwurf.eml", raw=True)
def entwurf(ctx):
    """Mail-Entwurf mit der zuvor abgelegten verschlüsselten Datei als Anhang."""
    _need(ctx)
    e = einstellungen(ctx.db.conn)
    name = Path(ctx.qp("datei") or "").name
    stand = _stand(ctx, ctx.qp("stand"))
    pfad = verzeichnis(ctx.db, e) / name
    if not name or not name.lower().endswith(".xlsx") or not pfad.is_file():
        raise ApiError(404, "Datei nicht gefunden – bitte zuerst verteilen")
    data = pfad.read_bytes()
    if not office_crypto.ist_verschluesselt(data):
        raise ApiError(400, "Datei ist nicht verschlüsselt")
    return {"_raw": eml(e, stand, name, data, _absender(ctx)), "_filename": f"Fertigungsbesprechung {stand}.eml",
            "_mime": "message/rfc822", "_inline": False}

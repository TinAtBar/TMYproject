"""R26-F: Wartung – Versionen, Lebenszyklus, Update-Prüfung, KI-Wartungsaufträge (GitHub-Issues mit @claude).

Reine Logik (ohne tkinter) – die Seite in barlagepm_admin.py nutzt diese Funktionen; Tests laufen ohne Netz.
Firmeneinstellungen (firma_einstellungen):
  wartung.github_repo   "owner/repo"            – optional; nur dann wird GitHub abgefragt
  wartung.github_token  Personal Access Token   – optional; nötig für private Repos und für Issues
  wartung.ki_vorlagen   [{"name", "text"}]       – Prompt-Vorlagen
"""
import datetime as _dt
import json
import platform
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

K_REPO, K_TOKEN, K_VORLAGEN = "wartung.github_repo", "wartung.github_token", "wartung.ki_vorlagen"

# Ende der Sicherheits-Updates (python.org, PEP 664/693/719)
PYTHON_EOL = {(3, 10): "2026-10", (3, 11): "2027-10", (3, 12): "2028-10", (3, 13): "2029-10", (3, 14): "2030-10"}

STANDARD_VORLAGEN = [
    {"name": "Sicherheits-Update prüfen",
     "text": "Bitte prüfe Barlage PM auf bekannte Sicherheitslücken: Python-Version ({python}), verwendete "
             "Standardbibliotheks-Funktionen (ssl, sqlite3, http.server), gebündelte Abhängigkeiten im Installer "
             "(PyInstaller, pystray, Pillow) und die TLS-Einstellungen des Servers. Erstelle für nötige Änderungen "
             "einen Pull Request mit Tests und einer kurzen Erklärung auf Deutsch."},
    {"name": "Abhängigkeiten aktualisieren",
     "text": "Bitte aktualisiere die Build-Abhängigkeiten von Barlage PM (Python {python}, PyInstaller, Inno Setup, "
             "pystray/Pillow) auf aktuelle, unterstützte Versionen. Lass alle Tests laufen "
             "(python -m unittest discover -s tests) und beschreibe Auswirkungen auf die Installation im LAN."},
    {"name": "Fehlerbericht analysieren",
     "text": "Bitte analysiere den folgenden Fehlerbericht aus Barlage PM (App {app}, Server {server}, "
             "DB-Schema {schema}) und schlage eine Korrektur als Pull Request vor:\n\n<Fehlerbericht hier einfügen>"},
]

HINWEIS_CLAUDE = ("Damit Claude auf „@claude“ in einem Issue reagiert, muss im GitHub-Repository die Claude-GitHub-App "
                  "installiert und die GitHub Action (anthropics/claude-code-action) mit API-Schlüssel eingerichtet sein. "
                  "Claude erstellt dann einen Pull Request – eingespielt wird erst nach Prüfung und neuem Installer.")


# ---------------------------------------------------------------- Versionen
def _lese_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def versionen(data_dir=None, conn=None, core=None, admin_version=None):
    """Installierte Versionen (ohne Netzwerk). core: barlagepm_core-Modul (optional, für App-Version/Lock)."""
    out = {"app": getattr(core, "VERSION", None) or "—", "admin": admin_version or getattr(core, "VERSION", None) or "—",
           "server": "—", "schema": "—", "python": platform.python_version(),
           "windows": windows_text(), "installer": "—"}
    if conn is not None:
        try:
            r = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
            out["schema"] = str(r[0]) if r else "—"
            n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            out["schema"] += f" ({n} Tabellen)"
        except Exception:  # noqa: BLE001
            pass
    if data_dir is not None:
        if core is not None:
            try:
                lock = core.lock_lesen(data_dir)
                if lock and core.lock_lebt(lock):
                    out["server"] = str(lock.get("version") or "läuft (Version unbekannt)")
                elif lock:
                    out["server"] = "kein Server aktiv"
            except Exception:  # noqa: BLE001
                pass
        d = _lese_json(Path(data_dir) / "installation" / "version.json")
        if d:
            out["installer"] = str(d.get("version") or "—")
    return out


def windows_text():
    if sys.platform != "win32":
        return f"{platform.system()} {platform.release()}"
    try:
        build = int(platform.version().split(".")[-1])
    except ValueError:
        build = 0
    return f"Windows {'11' if build >= 22000 else platform.release()} (Build {build or platform.version()})"


def lebenszyklus(python_version=None, heute=None, windows=None):
    """Liste von (stufe, text): stufe ok|warn|fehler."""
    heute = heute or _dt.date.today()
    pv = python_version or sys.version_info[:2]
    hinweise = []
    eol = PYTHON_EOL.get(tuple(pv[:2]))
    if eol:
        j, m = (int(x) for x in eol.split("-"))
        monate = (j - heute.year) * 12 + (m - heute.month)
        txt = f"Python {pv[0]}.{pv[1]}: Sicherheits-Updates bis {m:02d}/{j}"
        stufe = "fehler" if monate < 0 else ("warn" if monate < 12 else "ok")
        if stufe != "ok":
            txt += " – Umstieg auf neuere Python-Version mit dem nächsten Installer einplanen"
        hinweise.append((stufe, txt))
    else:
        hinweise.append(("warn", f"Python {pv[0]}.{pv[1]}: Support-Ende unbekannt – bitte prüfen"))
    w = windows or windows_text()
    if w.startswith("Windows 10"):
        hinweise.append(("warn", "Windows 10: regulärer Support endete am 14.10.2025 (ESU längstens bis 13.10.2026) – "
                                  "Server-PC auf Windows 11 umstellen"))
    elif w.startswith("Windows 11"):
        hinweise.append(("ok", "Windows 11: Funktionsupdates aktuell halten (jede Version hat 24 bzw. 36 Monate Support)"))
    else:
        hinweise.append(("ok", f"Betriebssystem: {w}"))
    return hinweise


# ---------------------------------------------------------------- Update-Prüfung
def _vt(v, core=None):
    if core is not None and hasattr(core, "version_tuple"):
        return core.version_tuple(v)
    out = [int("".join(ch for ch in t if ch.isdigit()) or 0) for t in str(v or "0").lstrip("vV").split(".")]
    return tuple(out + [0] * (4 - len(out)))


def update_lokal(data_dir, aktuell, core=None):
    """Liest <data>/installation/version.json (Update-Mechanismus der Desktop-App)."""
    d = _lese_json(Path(data_dir) / "installation" / "version.json")
    if not d:
        return {"gefunden": False, "text": "Keine version.json im Ordner „installation“ des Datenordners."}
    v = str(d.get("version") or "")
    neuer = _vt(v, core) > _vt(aktuell, core)
    return {"gefunden": True, "version": v, "neuer": neuer, "installer": d.get("installer"),
            "text": (f"Neuere Version {v} liegt bereit – die PCs aktualisieren sich beim nächsten Start."
                     if neuer else f"Installationsordner: Version {v} (aktuell).")}


def _req(url, token=None, daten=None, methode="GET", timeout=8, oeffner=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "BarlagePM-Admin",
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    body = None
    if daten is not None:
        body = json.dumps(daten).encode("utf-8")
        h["Content-Type"] = "application/json"
    rq = urllib.request.Request(url, data=body, headers=h, method=methode)
    with (oeffner or urllib.request.urlopen)(rq, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def repo_gueltig(repo):
    return bool(repo) and bool(re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", repo))


def github_release(repo, token=None, aktuell=None, oeffner=None, timeout=8):
    """Neueste Release-Version aus GitHub. Netzwerkfehler werden als Text zurückgegeben, nie geworfen."""
    if not repo:
        return {"ok": False, "text": "Kein GitHub-Repository hinterlegt – Abfrage übersprungen."}
    if not repo_gueltig(repo):
        return {"ok": False, "text": f"Repository „{repo}“ ungültig (Form: besitzer/name)."}
    try:
        d = _req(f"https://api.github.com/repos/{repo}/releases/latest", token, timeout=timeout, oeffner=oeffner)
    except urllib.error.HTTPError as e:
        t = {401: "Token ungültig", 403: "Zugriff verweigert/Limit erreicht", 404: "kein Release gefunden (oder privat ohne Token)"}
        return {"ok": False, "text": f"GitHub: {t.get(e.code, f'Fehler {e.code}')}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "text": f"GitHub nicht erreichbar ({getattr(e, 'reason', e)})."}
    v = str(d.get("tag_name") or d.get("name") or "").lstrip("vV")
    neuer = bool(aktuell) and _vt(v) > _vt(aktuell)
    return {"ok": True, "version": v, "url": d.get("html_url"), "neuer": neuer,
            "text": f"GitHub: neueste Version {v}" + (" – neuer als installiert" if neuer else " (installiert ist aktuell)")}


# ---------------------------------------------------------------- KI-Wartungsaufträge
def vorlagen(werte):
    v = werte.get(K_VORLAGEN) if isinstance(werte, dict) else None
    return v if isinstance(v, list) and v else [dict(x) for x in STANDARD_VORLAGEN]


def text_fuellen(text, vers):
    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return text.format_map(_D(vers or {}))


def issue_body(text):
    t = (text or "").strip()
    return t if t.startswith("@claude") else "@claude " + t


def issue_anlegen(repo, token, titel, text, oeffner=None, timeout=10):
    """POST /repos/{repo}/issues. Ohne Token/Repo: {"ok": False, "zwischenablage": True}. Wirft nie."""
    body = issue_body(text)
    if not token or not repo_gueltig(repo or ""):
        return {"ok": False, "zwischenablage": True, "body": body,
                "text": "Kein Repository/Token hinterlegt – Text wurde in die Zwischenablage kopiert."}
    try:
        d = _req(f"https://api.github.com/repos/{repo}/issues", token, {"title": titel or "Wartungsauftrag", "body": body},
                 "POST", timeout=timeout, oeffner=oeffner)
    except urllib.error.HTTPError as e:
        return {"ok": False, "zwischenablage": True, "body": body,
                "text": f"GitHub lehnte ab (Fehler {e.code}) – Text wurde in die Zwischenablage kopiert."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "zwischenablage": True, "body": body,
                "text": f"GitHub nicht erreichbar ({getattr(e, 'reason', e)}) – Text in der Zwischenablage."}
    return {"ok": True, "url": d.get("html_url"), "nummer": d.get("number"), "body": body,
            "text": f"Issue #{d.get('number')} angelegt."}


FELDER = [
    {"key": K_REPO, "label": "GitHub-Repository", "typ": "text", "default": "",
     "hilfe": "Form besitzer/name. Leer = keine GitHub-Abfrage."},
    {"key": K_TOKEN, "label": "GitHub-Token", "typ": "passwort", "default": "",
     "hilfe": "Fein-granulares Token mit Rechten „Contents: read“ und „Issues: write“ nur für dieses Repository. "
              "Wird in der Datenbank gespeichert – nur Admins sehen die Admin-Konsole."},
    {"key": K_VORLAGEN, "label": "KI-Prompt-Vorlagen", "typ": "liste", "default": [],
     "hilfe": "Platzhalter: {app} {admin} {server} {schema} {python} {windows}. Leer = Standardvorlagen.",
     "spalten": [{"key": "name", "label": "Name", "typ": "text", "pflicht": True},
                 {"key": "text", "label": "Auftrag", "typ": "text", "pflicht": True}]},
]

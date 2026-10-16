"""R26-F: „Status/Verbindung“ in Klartext (reine Logik, ohne tkinter)."""
import datetime as _dt
import socket


def _zeit(s):
    try:
        return _dt.datetime.fromisoformat(str(s)[:19])
    except (TypeError, ValueError):
        return None


def dauer_text(sek):
    sek = int(max(0, sek))
    if sek < 90:
        return f"{sek} Sekunden"
    if sek < 5400:
        return f"{sek // 60} Minuten"
    if sek < 172800:
        return f"{sek // 3600} Stunden"
    return f"{sek // 86400} Tagen"


def erreichbar(ip, port, timeout=0.8):
    """TCP-Verbindung zum Server möglich? (kein HTTP, nur Port-Test)."""
    if not ip or not port:
        return False
    try:
        with socket.create_connection((str(ip), int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def klartext(status, jetzt=None, rev=None, port_ok=None):
    """status: admin_core.Konsole.status(). Gibt [(stufe, titel, text)] mit stufe ok|warn|fehler|info."""
    jetzt = jetzt or _dt.datetime.now()
    lock = status.get("lock") or {}
    out = []
    if status.get("lebt"):
        seit = _zeit(lock.get("since"))
        hb = _zeit(lock.get("heartbeat"))
        txt = f"Der PC „{lock.get('host') or '?'}“ ist der Server"
        if lock.get("user"):
            txt += f" (gestartet von Benutzer {lock['user']})"
        if seit:
            txt += f", seit {seit:%d.%m.%Y %H:%M} Uhr (vor {dauer_text((jetzt - seit).total_seconds())})"
        out.append(("ok", "Wer ist Server?", txt + "."))
        adr = f"{lock.get('ip')}:{lock.get('port')}"
        if port_ok is None:
            out.append(("info", "Erreichbarkeit", f"Adresse {adr} – nicht geprüft."))
        elif port_ok:
            out.append(("ok", "Erreichbarkeit", f"Der Server antwortet unter {adr}. Andere PCs im Netz können sich verbinden."))
        else:
            out.append(("fehler", "Erreichbarkeit",
                        f"Der Server ist unter {adr} von diesem PC aus NICHT erreichbar. Mögliche Ursachen: "
                        "Firewall auf dem Server-PC, anderes Netz/VPN, PC im Ruhezustand."))
        if hb:
            alter = (jetzt - hb).total_seconds()
            if alter < 60:
                out.append(("ok", "Abgleich", f"Letztes Lebenszeichen vor {dauer_text(alter)} – Änderungen werden "
                                              "laufend an alle verbundenen Geräte verteilt."))
            else:
                out.append(("warn", "Abgleich", f"Letztes Lebenszeichen vor {dauer_text(alter)} – der Server reagiert "
                                                "verzögert. Geräte arbeiten ggf. offline und gleichen später ab."))
    elif lock:
        hb = _zeit(lock.get("heartbeat"))
        wann = f" (zuletzt {hb:%d.%m.%Y %H:%M})" if hb else ""
        out.append(("warn", "Wer ist Server?", f"Zurzeit kein Server. Zuletzt war „{lock.get('host')}“ Server{wann}. "
                                               "Sobald ein Projektleiter Barlage PM öffnet, übernimmt sein PC."))
        out.append(("info", "Abgleich", "Ohne Server arbeiten die Geräte offline; Änderungen werden beim nächsten "
                                        "Serverstart abgeglichen. Die Admin-Konsole spielt Änderungen direkt ein."))
    else:
        out.append(("info", "Wer ist Server?", "Noch nie ein Server gestartet. Ein Projektleiter startet ihn, indem er "
                                               "Barlage PM öffnet."))
    if rev is not None:
        out.append(("info", "Datenstand", f"Änderungszähler {rev} (steigt mit jeder gespeicherten Änderung)."))
    if status.get("fehler"):
        out.append(("warn", "Hinweis", str(status["fehler"])))
    return out


def pfade(conn):
    """Ruft ablage.pfade_pruefen auf, falls vorhanden. → (liste|None, hinweis)."""
    try:
        import ablage
        fn = getattr(ablage, "pfade_pruefen", None)
    except Exception:  # noqa: BLE001 – Modul fehlt/anders
        fn = None
    if fn is None:
        return None, "Dokumentenablage-Prüfung ist in dieser Version nicht verfügbar."
    try:
        return list(fn(conn) or []), ""
    except Exception as e:  # noqa: BLE001
        return None, f"Pfad-Prüfung fehlgeschlagen: {e}"

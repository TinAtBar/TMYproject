"""SQLite-Zugriff, Schema und der verbindliche Schreibpfad.

Eine einzige Verbindung, geschützt durch ein RLock. Alle Schreibvorgänge laufen
über Database.write(), das Idempotenz (applied_changes), Protokoll (jsonl + fsync
vor COMMIT), rev-Zähler und Transaktion erledigt.
"""
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path

from util import ApiError, now_iso, dumps

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  rolle TEXT NOT NULL CHECK (rolle IN ('admin','pm','mitarbeiter','controlling','leiter')),  -- R29-F: + leiter
  pw_hash TEXT, pw_salt TEXT, muss_pw_aendern INTEGER DEFAULT 0, aktiv INTEGER DEFAULT 1,
  urlaub INTEGER DEFAULT 0, letzte_anmeldung TEXT, vorletzte_anmeldung TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  erstellt TEXT, zuletzt TEXT);
CREATE TABLE IF NOT EXISTS projekte(
  id INTEGER PRIMARY KEY, nummer TEXT UNIQUE NOT NULL, bezeichnung TEXT, kunde TEXT, ort TEXT,
  status TEXT DEFAULT 'aktiv' CHECK (status IN ('aktiv','abgeschlossen')), angebot_ref TEXT,
  erstellt_von INTEGER, erstellt_am TEXT, geaendert_am TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS projekt_pm(projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id), PRIMARY KEY(projekt_id, user_id));
CREATE TABLE IF NOT EXISTS baugruppen(
  id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  nummer TEXT UNIQUE NOT NULL, bezeichnung TEXT, sn_trenn TEXT DEFAULT '.',
  sn_art TEXT DEFAULT 'GROSS' CHECK (sn_art IN ('GROSS','klein','zahl','frei')),
  menge INTEGER DEFAULT 1, angebot_ref TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS bauteile(id INTEGER PRIMARY KEY, baugruppe_id INTEGER REFERENCES baugruppen(id) ON DELETE CASCADE,
  bezeichnung TEXT, zeichnung TEXT, menge REAL, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS seriennummern(id INTEGER PRIMARY KEY, baugruppe_id INTEGER REFERENCES baugruppen(id) ON DELETE CASCADE,
  bauteil_id INTEGER NULL REFERENCES bauteile(id) ON DELETE SET NULL, sn TEXT UNIQUE NOT NULL, status_text TEXT,
  version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS meilenstein_typen(id INTEGER PRIMARY KEY, name TEXT NOT NULL, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS meilensteine(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  baugruppe_id INTEGER NULL REFERENCES baugruppen(id) ON DELETE CASCADE, typ_id INTEGER REFERENCES meilenstein_typen(id),
  datum TEXT, erledigt INTEGER DEFAULT 0, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS budget_kategorien(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  parent_id INTEGER NULL REFERENCES budget_kategorien(id), pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS budgets(id INTEGER PRIMARY KEY, baugruppe_id INTEGER REFERENCES baugruppen(id) ON DELETE CASCADE,
  kategorie_id INTEGER REFERENCES budget_kategorien(id), stunden REAL, betrag REAL, UNIQUE(baugruppe_id, kategorie_id));
CREATE TABLE IF NOT EXISTS status_opl(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farbe TEXT,
  art TEXT CHECK (art IN ('offen','abgeschlossen')), pos INTEGER DEFAULT 0, ist_start INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS prioritaeten(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farbe TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kategorien(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farbe TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS opl(
  id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  baugruppe_id INTEGER NULL REFERENCES baugruppen(id) ON DELETE SET NULL,
  bauteil_id INTEGER NULL REFERENCES bauteile(id) ON DELETE SET NULL,
  sn_id INTEGER NULL REFERENCES seriennummern(id) ON DELETE SET NULL,
  titel TEXT NOT NULL, beschreibung TEXT, kategorie_id INTEGER NULL REFERENCES kategorien(id),
  verantwortlich_id INTEGER NULL REFERENCES users(id), prioritaet_id INTEGER REFERENCES prioritaeten(id),
  frist TEXT, status_id INTEGER REFERENCES status_opl(id), erstellt_von INTEGER, erstellt_am TEXT,
  geaendert_von INTEGER, geaendert_am TEXT, erledigt_am TEXT, version INTEGER DEFAULT 1, geloescht INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_opl_projekt ON opl(projekt_id);
CREATE INDEX IF NOT EXISTS ix_opl_verantw ON opl(verantwortlich_id);
CREATE TABLE IF NOT EXISTS kommentare(id INTEGER PRIMARY KEY, opl_id INTEGER NULL, angebot_id INTEGER NULL,
  user_id INTEGER, text TEXT, zeit TEXT);
CREATE TABLE IF NOT EXISTS dateien(id INTEGER PRIMARY KEY, opl_id INTEGER NULL, projekt_id INTEGER NULL, angebot_id INTEGER NULL,
  name TEXT, pfad TEXT, mime TEXT, groesse INTEGER, user_id INTEGER, zeit TEXT);
CREATE TABLE IF NOT EXISTS status_angebot(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farbe TEXT,
  art TEXT CHECK (art IN ('offen','abgeschlossen')), pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS angebote(id INTEGER PRIMARY KEY, nummer TEXT, art TEXT CHECK (art IN ('angebot','nachtrag')),
  projekt_id INTEGER NULL REFERENCES projekte(id) ON DELETE SET NULL, bezeichnung TEXT, kunde TEXT,
  eigentuemer_id INTEGER REFERENCES users(id), status_id INTEGER REFERENCES status_angebot(id), betrag REAL,
  versendet_am TEXT, wiedervorlage TEXT, beauftragt_projekt_id INTEGER NULL, version INTEGER DEFAULT 1,
  geloescht INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS angebot_freigaben(angebot_id INTEGER REFERENCES angebote(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id), PRIMARY KEY(angebot_id, user_id));
-- Ergänzung zur SPEC: Positionen eines Angebots (werden bei Umwandlung zu Baugruppen)
CREATE TABLE IF NOT EXISTS angebot_positionen(id INTEGER PRIMARY KEY, angebot_id INTEGER REFERENCES angebote(id) ON DELETE CASCADE,
  nummer TEXT, bezeichnung TEXT, menge INTEGER DEFAULT 1, budgets TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, zeit TEXT, user_id INTEGER,
  objekt TEXT, objekt_id INTEGER, projekt_id INTEGER, aktion TEXT, details TEXT);
CREATE INDEX IF NOT EXISTS ix_act_zeit ON activity(zeit);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS applied_changes(change_id TEXT PRIMARY KEY, zeit TEXT, antwort TEXT);
"""


class Database:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "opl.db"
        self.protokoll_dir = self.data_dir / "protokoll"
        self.dateien_dir = self.data_dir / "dateien"
        for d in (self.data_dir, self.protokoll_dir, self.dateien_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.fts = self._init_fts()
        for k, v in (("rev", "0"), ("schema_version", SCHEMA_VERSION)):
            self.conn.execute("INSERT OR IGNORE INTO meta(k,v) VALUES(?,?)", (k, v))

    # ---------------------------------------------------------------- Ergänzungen (additiv, idempotent)
    MIGRATION_SPALTEN = (
        ("budgets", "ist_stunden", "REAL"), ("budgets", "ist_betrag", "REAL"),
        ("meilensteine", "ist_datum", "TEXT"),
        ("seriennummern", "fertigungsstatus_id", "INTEGER"),
    )
    MIGRATION_TABELLEN = """
CREATE TABLE IF NOT EXISTS fertigungsstatus(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farbe TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS benachrichtigungen(id INTEGER PRIMARY KEY, user_id INTEGER, zeit TEXT, art TEXT, text TEXT,
  link TEXT, objekt TEXT, objekt_id INTEGER, von_id INTEGER, gelesen INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_benachr_user ON benachrichtigungen(user_id, gelesen);
CREATE TABLE IF NOT EXISTS opl_vorlagen(id INTEGER PRIMARY KEY, name TEXT NOT NULL, punkte TEXT, pos INTEGER DEFAULT 0);
-- mobile: Geräte-Kopplung (QR) und PIN
CREATE TABLE IF NOT EXISTS geraete(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name TEXT, token TEXT UNIQUE, erstellt TEXT, zuletzt TEXT, pin_hash TEXT, pin_salt TEXT,
  fehlversuche INTEGER DEFAULT 0, sperre_bis TEXT, gesperrt INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kopplungen(token TEXT PRIMARY KEY, user_id INTEGER, erstellt REAL, gueltig_bis REAL,
  benutzt INTEGER DEFAULT 0);
"""

    def _migrate(self):
        self.conn.executescript(self.MIGRATION_TABELLEN)
        import markierung; markierung.migration(self.conn)  # R3-B: opl.zustaendig_text, projekte.notizen
        import datenpaket; datenpaket.migration(self.conn)  # R3-D: Datenübernahme (idempotent)
        import qip, kickoff; qip.migration(self.conn); kickoff.migration(self.conn)  # R3-C: QIP + Kick-Off
        import domaene; domaene.migration(self.conn)  # R28-G1: users.windows_login
        for t, col, typ in self.MIGRATION_SPALTEN:
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({t})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
        # Logins sind ohne Groß-/Kleinschreibung eindeutig. Gibt es (Altbestand) Dubletten,
        # bleibt der Index weg; die Anmeldung bevorzugt dann den exakt geschriebenen Login.
        try:
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_login_nocase ON users(login COLLATE NOCASE)")
        except sqlite3.IntegrityError:
            pass
        if not self.conn.execute("SELECT 1 FROM fertigungsstatus").fetchone():
            for i, (n, f) in enumerate([("geplant", "#6b7380"), ("in Fertigung", "#b06a00"),
                                        ("geprüft", "#1f6f9f"), ("ausgeliefert", "#2a6b3f")]):
                self.conn.execute("INSERT INTO fertigungsstatus(name,farbe,pos) VALUES(?,?,?)", (n, f, i))
        if not self.conn.execute("SELECT 1 FROM opl_vorlagen").fetchone():
            punkte = [{"titel": t, "kategorie": "Klärung", "frist_tage": d} for t, d in (
                ("Maßkontrolle nach Zeichnung", 3), ("Druckprüfung / Dichtheitsprüfung dokumentiert", 5),
                ("Oberflächenbehandlung (OT) abgenommen", 5), ("Typenschild angebracht", 7),
                ("Dokumentation / Prüfbescheinigungen vollständig", 10), ("Endabnahme mit Kunde", 14))]
            self.conn.execute("INSERT INTO opl_vorlagen(name,punkte,pos) VALUES(?,?,0)",
                              ("Endabnahme-Checkliste", json.dumps(punkte, ensure_ascii=False)))
        import archiv; archiv.migration(self.conn)  # R3-A: Archiv-Spalten + users.darstellung
        import zustaendig; zustaendig.migration(self.conn)  # R5-Z: opl_zustaendig, users.email, kontakte
        import termine; termine.migration(self.conn); markierung.migration_import(self.conn)  # R4-P: freie Termine, Import ≠ neu
        import prefs; prefs.migration(self.conn)  # R4-T: Benutzer-Einstellungen (user_prefs)
        import fertigung; fertigung.migration(self.conn)  # R5-F: Allgemein, Projektkopf, Sitzungen
        import rechte; rechte.migration(self.conn)  # R26-E: Rolle controlling
        import ablage; ablage.migration(self.conn)  # R26-B: Dokumentenablage (+ firma_einstellungen)
        import firma; firma.migration(self.conn)  # R26-F: Firmeneinstellungen (Key-Value)
        import meilensteine, fortschritt; meilensteine.migration(self.conn); fortschritt.migration(self.conn)  # R26-C1: Meilensteine je Projekt, Fortschritt-Verlauf
        import budget, reststunden; budget.migration(self.conn); reststunden.migration(self.conn)  # R26-C2: Ist-Stunden, Reststunden-Abrufe
        import masken; masken.migration(self.conn)  # R26-H: Zusatzfeld-Werte
        import vertretung, fertigung_antraege; vertretung.migration(self.conn); fertigung_antraege.migration(self.conn)  # R27-103–105
        import dashboard; dashboard.migration(self.conn)  # R27: Dashboard 2 (Kennzahl-Verlauf, eigene Dashboards)
        import bestellung; bestellung.migration(self.conn)  # R27-106: Kundenbestellung + Dokumenttyp „Bestellung“
        import freigaben; freigaben.migration(self.conn)  # R28-G11: Hochladen mit Freigabe (ablage_freigaben)
        import tickets; tickets.migration(self.conn)  # R28-G10: Problem melden / Idee (Tickets)
        import eingang; eingang.migration(self.conn)  # R29-B (128): Import/Eingangskorb
        import vorschlaege; vorschlaege.migration(self.conn)  # R29-F (109): Punkt vorschlagen (nach freigaben)

    # ---------------------------------------------------------------- Suche-Index
    def _init_fts(self):
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS suche USING fts5("
                              "art UNINDEXED, ref_id UNINDEXED, projekt_id UNINDEXED, titel, text, "
                              "tokenize='unicode61 remove_diacritics 2')")
            return True
        except sqlite3.OperationalError:
            # Fallback: normale Tabelle, Suche per LIKE
            self.conn.execute("CREATE TABLE IF NOT EXISTS suche(art TEXT, ref_id INTEGER, projekt_id INTEGER, titel TEXT, text TEXT)")
            return False

    def index(self, conn, art, ref_id, projekt_id, titel, text):
        conn.execute("DELETE FROM suche WHERE art=? AND ref_id=?", (art, str(ref_id)))
        conn.execute("INSERT INTO suche(art, ref_id, projekt_id, titel, text) VALUES(?,?,?,?,?)",
                     (art, str(ref_id), str(projekt_id or ""), titel or "", text or ""))

    def unindex(self, conn, art, ref_id):
        conn.execute("DELETE FROM suche WHERE art=? AND ref_id=?", (art, str(ref_id)))

    # ---------------------------------------------------------------- Lesen
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def q1(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def rev(self):
        return int(self.q1("SELECT v FROM meta WHERE k='rev'")["v"])

    # ---------------------------------------------------------------- Schreiben
    def check_available(self):
        if not os.path.exists(self.db_path):
            raise ApiError(503, "Datenordner nicht erreichbar")

    def _protokoll(self, eintrag):
        datum = eintrag["zeit"][:10]
        pfad = self.protokoll_dir / f"changes-{datum}.jsonl"
        with open(pfad, "a", encoding="utf-8") as f:
            f.write(dumps(eintrag) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def write(self, user, aktion, fn, change_id=None, payload=None):
        """Führt fn(conn) als Schreibtransaktion aus. fn liefert die Antwort (dict).

        Ablauf: Verfügbarkeit → Idempotenz → fn (inkl. Konfliktprüfung) →
        Protokoll (fsync) → rev+1, applied_changes → COMMIT.
        """
        self.check_available()
        change_id = change_id or str(uuid.uuid4())
        with self.lock:
            c = self.conn
            r = c.execute("SELECT antwort FROM applied_changes WHERE change_id=?", (change_id,)).fetchone()
            if r:
                return json.loads(r[0])
            c.execute("BEGIN IMMEDIATE")
            try:
                antwort = fn(c)
                self._protokoll({"change_id": change_id, "zeit": now_iso(),
                                 "user_id": user["id"] if user else None, "aktion": aktion,
                                 "daten": payload})
                c.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k='rev'")
                c.execute("INSERT INTO applied_changes(change_id, zeit, antwort) VALUES(?,?,?)",
                          (change_id, now_iso(), dumps(antwort)))
                c.execute("COMMIT")
                return antwort
            except BaseException:
                c.execute("ROLLBACK")
                raise

    # Zusatz-Hooks (z. B. Benachrichtigungen), aufgerufen innerhalb derselben Transaktion
    activity_hooks = []

    @staticmethod
    def activity(conn, user, objekt, objekt_id, projekt_id, aktion, details=None):
        if user and user.get("_zusatz"):  # R27-104/105: „Antrag #x von …“, „als Vertretung für …“
            details = {**(details or {}), **user["_zusatz"]}
        conn.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,?,?,?,?,?,?)",
                     (now_iso(), user["id"] if user else None, objekt, objekt_id, projekt_id, aktion,
                      dumps(details or {})))
        for hook in Database.activity_hooks:
            try:
                hook(conn, user, objekt, objekt_id, projekt_id, aktion, details or {})
            except Exception as e:  # Hooks dürfen den Schreibvorgang nie verhindern
                print("Activity-Hook fehlgeschlagen:", e)

    def close(self):
        with self.lock:
            self.conn.close()

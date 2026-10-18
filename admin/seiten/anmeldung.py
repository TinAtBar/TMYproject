"""R28-G1: Admin-Seite „Anmeldung“ (Beschreibung: docs/admin-seiten/anmeldung.md).

Firmeneinstellungen anmeldung.domaene / anmeldung.modus. Den Windows-Benutzer je Person pflegt die Seite
„Benutzer & Rollen“ (Feld „Windows-Benutzer“).
"""
K_DOMAENE = "anmeldung.domaene"
K_MODUS = "anmeldung.modus"
MODI = (("beides", "beides – Windows-Benutzer per Windows, alle anderen lokal"),
        ("domaene", "nur Domäne – lokale Anmeldung nur noch für Administratoren"),
        ("lokal", "lokal – Domäne aus, alle mit App-Passwort"))
TEXT = ("Anmeldung mit Windows-Benutzer und Windows-Passwort (Domäne). Der Server-PC prüft das Passwort bei Windows; "
        "Barlage PM speichert es nicht. Personen ohne Windows-Benutzer melden sich weiter mit dem App-Passwort an. "
        "Administratoren können sich immer zusätzlich mit ihrem lokalen Passwort anmelden (Notfall).")

FELDER = [
    {"key": K_DOMAENE, "label": "Domäne", "typ": "text", "default": "", "abschnitt": "Windows-Domäne",
     "hilfe": "Name der Windows-Domäne, z. B. FIRMA. Leer = Domänen-Anmeldung aus."},
    {"key": K_MODUS, "label": "Anmeldemodus", "typ": "text", "default": "beides", "optionen": [m[0] for m in MODI],
     "hilfe": " · ".join(m[1] for m in MODI)},
]


def baue(k, rahmen):
    k._mehrere(rahmen, [(k.tab_firma, "anmeldung", "Anmeldung", TEXT, FELDER)])


def registrieren():
    import seiten
    seiten.registrieren("anmeldung", "Anmeldung", "🔑", seiten.GRUPPEN[0], baue,
                        "Windows-Domäne, Anmeldemodus, Notfall-Admin")

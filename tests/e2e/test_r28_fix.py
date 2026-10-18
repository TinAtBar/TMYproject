"""R28-FIX: Prüfungen zu den Restfehlern aus dem Klicktest (Angebots-Freigaben, Fertigungsbesprechung-Kopf,
gleich hohe Kennzahl-Kacheln im Glas-Stil auf dem Handy, eindeutige Kalender-Beschriftung, Datumsachse Verlauf)."""
import datetime

from .helfer import E2EBasis, oeffne, ruhe


class R28Fix(E2EBasis):
    def test_angebot_freigabe_ohne_controlling(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/angebote")
        page.locator(".tbl tbody tr").first.click()
        ruhe(page)
        namen = page.evaluate("() => [...document.querySelectorAll('dialog[open] .chips label.toggle')].map(e => e.innerText.trim())")
        self.shot(page, "fix1-angebot-freigaben")
        self.assertNotIn("Controlling A", namen)
        self.assertFalse(any("Admin" in n for n in namen), namen)
        self.assertIn("Projektleiter B", namen)
        self.sauber(w, "Angebot-Freigaben")

    def test_fertigung_kopf(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/fertigung")
        page.wait_for_selector(".fb-actions")
        stand = page.locator(".fb-stand strong").inner_text().strip()
        self.assertRegex(stand, r"^\d\d\.\d\d\.\d{4}$")
        blatt = page.evaluate("() => { const dt = [...document.querySelectorAll('.fb-meta dt')].find(e => e.textContent === 'Stand:'); return dt ? dt.nextElementSibling.textContent.trim() : null; }")
        if blatt:
            self.assertEqual(stand, blatt)
        # „OPL“ steht nie allein in einer Zeile der Werkzeugleiste
        allein = page.evaluate("""() => { const a = [...document.querySelectorAll('.fb-actions > *, .fb-actions-2 > *')].filter(e => e.offsetParent && !e.classList.contains('fb-actions-2'));
            const opl = a.find(e => e.textContent.trim() === 'OPL'); if (!opl) return false; const y = opl.getBoundingClientRect().top;
            return a.filter(e => Math.abs(e.getBoundingClientRect().top - y) < 4).length === 1; }""")
        self.shot(page, "fix2-fertigung")
        self.assertFalse(allein, "„OPL“ allein in einer Zeile")
        self.sauber(w, "Fertigung")

    def test_kennzahlen_gleich_hoch_handy_glas(self):
        page, w = self.seite("pm1", handy=True, dstil="glas")
        oeffne(page, "#/start")
        page.wait_for_selector(".dk-kz")
        page.wait_for_timeout(600)
        reihen = page.evaluate("""() => { const m = {}; for (const k of document.querySelectorAll('.dk-karte.dk-kz')) {
            const r = k.getBoundingClientRect(); const y = Math.round(r.top / 10); (m[y] = m[y] || []).push(Math.round(r.height)); } return Object.values(m); }""")
        self.shot(page, "fix3-kennzahlen-handy-glas")
        for r in reihen:
            self.assertLessEqual(max(r) - min(r), 2, f"Kacheln ungleich hoch: {reihen}")
        self.sauber(w, "Kennzahlen Handy")

    def test_kalender_beschriftung(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/kalender")
        page.wait_for_selector(".cal-head select")
        opt = page.locator(".cal-head select option").first.inner_text()
        knopf = page.locator(".cal-head button.toggle").inner_text().strip()
        self.shot(page, "fix4-kalender")
        self.assertNotEqual(opt.strip(), knopf)
        self.assertEqual(page.get_by_text("Alle Projekte", exact=True).count(), 0)
        self.sauber(w, "Kalender")

    def test_verlauf_ticks_lueckenlos(self):
        page, w = self.seite("pm1")
        # direkt die Diagramm-Funktion mit Daten über die Zeitumstellung (25.10.2026) prüfen
        tage = page.evaluate("""async () => { const m = await import('/js/views/projekt-fortschritt.js');
            const p = []; for (let d = 18; d <= 28; d++) p.push({ datum: `2026-10-${d}`, fortschritt_prozent: d * 2, stunden_prozent: d * 3 });
            const svg = m.verlaufSvg(p, null); document.body.append(svg);
            const t = [...svg.querySelectorAll('text[data-tag]')].map(e => e.getAttribute('data-tag')); svg.remove(); return t; }""")
        self.assertGreaterEqual(len(tage), 3, tage)
        ds = [datetime.date.fromisoformat(t) for t in tage]
        abst = {(b - a).days for a, b in zip(ds, ds[1:])}
        self.assertEqual(len(abst), 1, f"ungleichmäßige Ticks: {tage}")
        self.assertIn("2026-10-21", tage) if abst == {1} else None
        oeffne(page, "#/projekte/1")
        self.shot(page, "fix5-projekt")
        self.sauber(w, "Verlauf")

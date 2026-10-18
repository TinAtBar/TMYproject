"""R28: Playwright-Ende-zu-Ende-Suite (tests/e2e/). Übersprungen, wenn Playwright/Chromium fehlt.

Aufruf:  python3 -m unittest tests.test_r28_e2e -v
Einzeln: python3 -m unittest tests.e2e.test_opl -v
Screenshots der Prüfungen: Umgebungsvariable BPM_E2E_SHOTS=<ordner>
"""
import os
import sys
import unittest
from pathlib import Path

HIER = Path(__file__).resolve().parent
if str(HIER.parent) not in sys.path:  # Repo-Wurzel → Paket „tests.e2e“
    sys.path.insert(0, str(HIER.parent))


def load_tests(loader, standard, muster):
    suite = unittest.TestSuite()
    try:
        import playwright  # noqa: F401
    except ImportError:
        class Fehlt(unittest.TestCase):
            @unittest.skip("Playwright nicht installiert")
            def test_e2e(self):
                pass
        suite.addTests(loader.loadTestsFromTestCase(Fehlt))
        return suite
    os.environ["BPM_E2E_RUNNER"] = "1"  # tests/e2e/__init__.py liefert die Tests nur über diesen Runner
    try:
        import importlib
        paket = importlib.import_module("tests.e2e")
        suite.addTests(paket.load_tests(loader, unittest.TestSuite(), "test_*.py"))
    finally:
        os.environ.pop("BPM_E2E_RUNNER", None)
    return suite

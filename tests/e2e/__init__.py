"""Playwright-Ende-zu-Ende-Suite für Barlage PM (R28). Runner: tests/test_r28_e2e.py.

Bei `unittest discover -s tests` liefert das Paket selbst keine Tests (sonst liefe die Suite doppelt);
sie kommt über tests/test_r28_e2e.py. Einzelne Module direkt: python3 -m unittest tests.e2e.test_opl
"""
import os


def load_tests(loader, standard, muster):
    import unittest
    if not os.environ.get("BPM_E2E_RUNNER"):
        return unittest.TestSuite()
    hier = os.path.dirname(os.path.abspath(__file__))
    standard.addTests(loader.discover(start_dir=hier, pattern=muster or "test_*.py",
                                      top_level_dir=os.path.dirname(os.path.dirname(hier))))
    return standard

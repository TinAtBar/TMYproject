"""R5-L: OPL-Filter mit Mehrfachwerten, Zuständig (Benutzer), Sekundärsortierung."""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402


class ListenR5Test(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def _ids(self, cl, q):
        st, d, _ = cl.get("/api/opl?status_art=alle&limit=5000&" + q)
        self.assertEqual(st, 200, d)
        return {i["id"] for i in d["items"]}

    def test_mehrfach_und_sortierung(self):
        a = self.c("admin")
        pr = a.get("/api/projekte")[1]
        pr = pr if isinstance(pr, list) else pr["items"]
        p1, p2 = pr[0]["id"], pr[1]["id"]
        alle = self._ids(a, "")
        n1, n2 = self._ids(a, f"projekt_id={p1}"), self._ids(a, f"projekt_id={p2}")
        self.assertEqual(self._ids(a, f"projekt_id={p1},{p2}"), n1 | n2)
        self.assertTrue(self._ids(a, f"projekt_id={p1},{p2}") <= alle)
        # Status mehrfach
        st = a.get("/api/stammdaten")[1]["status_opl"]
        s1, s2 = st[0]["id"], st[1]["id"]
        self.assertEqual(self._ids(a, f"status_id={s1},{s2}"), self._ids(a, f"status_id={s1}") | self._ids(a, f"status_id={s2}"))
        # Zuständig: zugewiesen oder Name im Text
        users = a.get("/api/stammdaten")[1]["users"]
        ma = next(u for u in users if u["login"] == "ma1") if "login" in users[0] else users[-1]
        oid = a.post("/api/opl", {"projekt_id": p1, "titel": "R5L Text", "zustaendig_text": "Werkstatt / " + ma["name"],
                                  "change_id": str(uuid.uuid4())})[1]["item"]["id"]
        z = self._ids(a, f"zustaendig_user_id={ma['id']}")
        self.assertIn(oid, z)
        self.assertNotIn(oid, self._ids(a, "zustaendig_user_id=null"))
        # Sekundärsortierung wird angenommen
        st_, d, _ = a.get("/api/opl?status_art=alle&sort=status,-frist")
        self.assertEqual(st_, 200, d)
        st_, d, _ = a.get("/api/opl?status_art=alle&sort=quatsch")
        self.assertEqual(st_, 200, d)


if __name__ == "__main__":
    unittest.main()

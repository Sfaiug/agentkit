"""`ak models --refresh` reads Artificial Analysis off its models list and the own page of each
release any page it reads hands: a row at an effort only a release's own page hands is rated, a
release first found on another's page is kept at every effort its own page hands, and a
release's page without a record of that release leaves the board as it was held, its error
beside it.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
site served on the loopback (`AK_AA_URL`); judged by `ak models --json` and the boards it keeps.
Fails against /bin/false.
"""

import http.server
import json
import sys
from pathlib import Path
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akboards import ENV, EVALUATIONS, SAME, boards

# (slug, name, release, intelligence index, frontier-code and terminal shares, cost a task)
LISTED = [("acme-mid-5", "Acme Mid 5 (Max)", "acme-mid-5", 68, 0.79, 16.0),
          ("bolt-3", "Bolt 3 (High)", "bolt-3", 62, 0.72, 4.0)]
# what only a release's own page hands: Acme Mid 5 at xhigh, Bolt 3 at medium
OWN = [("acme-mid-5-xhigh", "Acme Mid 5 (Xhigh)", "acme-mid-5", 67, 0.78, 14.0),
       ("bolt-3-medium", "Bolt 3 (Medium)", "bolt-3", 60, 0.70, 3.0)]
# a release the list does not name, found on Bolt 3's page at high, its own page handing it at
# high and medium
FOUND = [("crux-2-high", "Crux 2 (High)", "crux-2", 55, 0.65, 2.0),
         ("crux-2-medium", "Crux 2 (Medium)", "crux-2", 53, 0.63, 1.5)]


def page(records):
    """A page of the site: each record whole, in the data it hands its scripts."""
    data = json.dumps({"models": [{
        "id": f"{n:08x}-0000-4000-8000-000000000000", "slug": slug, "name": name,
        "intelligenceIndex": index, "frontierCode20": share, "terminalBench40": share,
        "briefcaseBreakdown": {"elo": SAME["aa.briefcaseBreakdown.overall.elo"]},
        "omniscience": SAME["aa.omniscience"],
        "automationBenchPartialScore": SAME["aa.automationBenchPartialScore"],
        "intelligenceIndexEvaluations": [{"slug": one, "costPerTask": cost} for one in EVALUATIONS],
        "deprecated": False, "release": {"slug": release, "name": name.split(" (")[0],
                                         "deprecatedTo": None},
        "creator": {"id": "00000000-0000-4000-8000-0000000000ac", "name": "Acme"}}
        for n, (slug, name, release, index, share, cost) in enumerate(records)]},
        separators=(",", ":"))
    return f"<script>self.__next_f.push([1,{json.dumps(data)}])</script>".encode()


def site(bolt=True):
    """Each path's page: the list, a release each at its top effort, and each release's own,
    every effort of it, the listed ones' beside another release's record; `bolt` False, Bolt 3's
    page without one of Bolt 3."""
    return {"/models": page(LISTED),
            "/models/acme-mid-5": page([LISTED[0], OWN[0], LISTED[1]]),
            "/models/bolt-3": page([LISTED[1], OWN[1], FOUND[0]] if bolt else [LISTED[0]]),
            "/models/crux-2": page(FOUND)}


class Site(http.server.ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Pages)
        self.pages = site()
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.server.pages.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")

    def log_message(self, *_):
        pass


class ModelsBoardsPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.site = Site()
        cls.addClassCleanup(cls.site.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                              "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})

    def refresh(self, pages):
        """`ak models --refresh --json` on the boards as test_key_models_answer.py holds them,
        the site handing `pages`: its answer, and the Artificial Analysis board held before and
        after."""
        held = boards()
        self.home.write(".agentkit/state/boards.json", held)
        self.site.pages = pages
        done = self.home.ak("models", "--refresh", "--json", env={
            **ENV, "no_proxy": "127.0.0.1",
            "AK_AA_URL": f"http://127.0.0.1:{self.site.server_address[1]}"})
        self.assertEqual(done.code, 0, done.err)
        kept = json.loads((self.home.path / ".agentkit/state/boards.json").read_text())
        return json.loads(done.out), held["artificialanalysis.ai"], kept["artificialanalysis.ai"]

    def test_a_row_at_an_effort_only_its_release_s_page_hands_is_rated(self):
        found, _, board = self.refresh(site())
        self.assertIsNone(board["error"])
        rated = {(row["name"], row["effort"]): row["quality"]
                 for key in ("front", "choices", "others") for row in found["execute"][key]}
        self.assertIsInstance(rated.get(("Acme Mid 5", "xhigh")), (int, float))

    def test_a_release_first_found_on_anothers_page_has_its_own_page_read_too(self):
        _, _, board = self.refresh(site())
        self.assertIsNone(board["error"])
        self.assertEqual({row["effort"] for row in board["rows"]
                          if row["release"]["slug"] == "crux-2"}, {"high", "medium"})

    def test_a_release_s_page_without_its_record_keeps_the_board_as_held(self):
        _, held, board = self.refresh(site(bolt=False))
        self.assertEqual((board["rows"], board["fetched_at"]), (held["rows"], held["fetched_at"]))
        self.assertIn("bolt-3", board["error"])


if __name__ == "__main__":
    unittest.main()

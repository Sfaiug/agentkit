"""`ak models --refresh` prices a role's row off Artificial Analysis's records as the site has
given them since 15 Nov 2026, no list of the index's evaluations: at the record's cost a task of
the role's evaluation weighted in the index, over that weight; and one record weighing an
evaluation ak knows no weight of leaves the board as it was held, that evaluation in its error.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_boards_pages.py sets it
up, the site served on the loopback (`AK_AA_URL`); judged by `ak models --json` and the boards it
keeps.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akboards import ENV, SAME, boards
from test_key_models_boards_pages import Site

# (slug, name, release, intelligence index, frontier-code and terminal shares, cost a task)
RECORDS = [("acme-mid-5", "Acme Mid 5 (Max)", "acme-mid-5", 68, 0.79, 16.0),
           ("bolt-3", "Bolt 3 (High)", "bolt-3", 62, 0.72, 4.0)]
# each role's evaluation and its weight in the index, as the site's methodology said of v5.0.1
WEIGHTS = {"aa-briefcase": 0.15, "frontiercode-2-0": 0.15}


def page(records, unweighed=()):
    """A page of the site: each record whole as it gives them now, its evaluations' costs a task
    weighted, Bolt 3's naming `unweighed` too."""
    data = json.dumps({"models": [{
        "id": f"{n:08x}-0000-4000-8000-000000000000", "slug": slug, "name": name,
        "intelligenceIndex": index, "frontierCode20": share, "terminalBench40": share,
        "briefcaseBreakdown": {"elo": SAME["aa.briefcaseBreakdown.overall.elo"]},
        "omniscience": SAME["aa.omniscience"],
        "automationBenchPartialScore": SAME["aa.automationBenchPartialScore"],
        "intelligenceIndexCostPerTask": {"evaluations": [
            {"slug": one, "weightedCostPerTask": cost * weight} for one, weight in WEIGHTS.items()]
            + [{"slug": one, "weightedCostPerTask": 1.0} for one in unweighed if slug == "bolt-3"]},
        "deprecated": False, "release": {"slug": release, "name": name.split(" (")[0],
                                         "deprecatedTo": None},
        "creator": {"id": "00000000-0000-4000-8000-0000000000ac", "name": "Acme"}}
        for n, (slug, name, release, index, share, cost) in enumerate(records)]},
        separators=(",", ":"))
    return f"<script>self.__next_f.push([1,{json.dumps(data)}])</script>".encode()


def site(unweighed=()):
    """Each path's page: the list and each release's own."""
    return {"/models": page(RECORDS, unweighed),
            **{f"/models/{record[2]}": page([record], unweighed) for record in RECORDS}}


class ModelsBoardsCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.site = Site()
        cls.addClassCleanup(cls.site.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\n")
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

    def test_a_role_s_row_costs_its_evaluation_s_weighted_cost_over_its_weight(self):
        found, _, board = self.refresh(site())
        self.assertIsNone(board["error"])
        for role in ("orchestrate", "execute"):
            priced = {(row["name"], row["effort"]): round(row["board_cost"], 9)
                      for key in ("front", "choices", "others") for row in found[role][key]}
            self.assertEqual(priced, {("Acme Mid 5", "max"): 16.0, ("Bolt 3", "high"): 4.0}, role)

    def test_a_record_weighing_an_evaluation_ak_lacks_keeps_the_board_as_held(self):
        _, held, board = self.refresh(site(unweighed=("acme-lore",)))
        self.assertEqual((board["rows"], board["fetched_at"]), (held["rows"], held["fetched_at"]))
        self.assertIn("acme-lore", board["error"])


if __name__ == "__main__":
    unittest.main()

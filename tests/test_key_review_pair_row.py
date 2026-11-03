"""A merged run records its review pair once; the history board shows their shares.

Black-box: AK_BIN, throwaway Homes and repositories, fake GitHub and scripted harnesses.
"""

import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_scoreboard import scoreboard


class ReviewPairRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env.pop("AK_NOTIFY_SINK")  # these runs must leave history, as the owner's do
        gh = GitHub(cls.home)
        fakeadapter.install(cls.home, claude="work", codex="work")
        cls.rows = {}
        for n, (pair, harness) in enumerate((("self", None), ("same provider", "claude"),
                                            ("other provider", "codex"))):
            rig = Rig(cls.home, f"widgets-{n}")
            base = rig.head()
            gh.grant(rig.slug, "WRITE")
            models = {"cedar": "claude", **({"birch": harness} if harness else {})}
            akconfig.write(cls.home, models, workers=["cedar"],
                           reviewers=["birch" if harness else "cedar"])
            task = taskfile.write(cls.home, rig.path, f"Add retry file {n}")
            done = cls.home.ak("run", str(task), timeout=300)
            assert done.code == 0, done.out + done.err
            assert rig.head() != base, done.out + done.err
            with sqlite3.connect(cls.home.path / ".agentkit/history.db") as db:
                cls.rows[pair] = db.execute(
                    "SELECT final_state, review_pair FROM runs WHERE repo=?", (rig.name,)).fetchone()
        cls.board = cls.home.ak("run", "status", "--history")

    def test_one_model_for_both_roles_records_self(self):
        self.assertEqual(self.rows["self"], ("pass", "self"))

    def test_two_models_of_one_provider_record_same_provider(self):
        self.assertEqual(self.rows["same provider"], ("pass", "same provider"))

    def test_two_models_of_two_providers_record_other_provider(self):
        self.assertEqual(self.rows["other provider"], ("pass", "other provider"))

    def test_history_shows_a_third_self_and_a_third_same_provider(self):
        self.assertEqual(self.board.code, 0, self.board.out + self.board.err)
        rows = {label: (now, before) for label, now, before in scoreboard(self.board.out)}
        now, before = rows["review pairs"]
        self.assertIn("33% self-reviewed", now)
        self.assertIn("33% reviewed by another model of the same provider", now)
        self.assertEqual(before, "not recorded")


if __name__ == "__main__":
    unittest.main()

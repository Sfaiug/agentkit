"""Two disputes of one finding reach the review together and count once in history and the ledger.

When a fixer hands in two accepted disputes with different reasons for the same blocking finding,
both reach the next review and result.md under that finding, while history.db's `findings` table
and `ak models --json`'s team counts record one issue, one disputed, and one taken back.

Black-box: the program `AK_BIN` names runs `ak run --no-merge` and `ak models --json` from outside
through tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses from
fakeadapter.py. Fails against /bin/false.
"""

import json
from pathlib import Path
import unittest

from test_key_fixer_dispute_run import start
from test_key_history_db import OWNERS, read
from test_key_models_answer import ENV, boards

FIRST = "the first dispute reason"
SECOND = "the second dispute reason"
CONCEDED = "The fixture is right."
FIXER = {"final": "Disputed twice.", "hand_in": [
    ["dispute", "retry.txt:1", FIRST, "--run", "echo first proof output"],
    ["dispute", "retry.txt:1", SECOND, "--quote", "hello"],
    ["done"]]}
CONCEDE = {"final": "Conceded.", "hand_in": [
    ["concede", "retry.txt:1", CONCEDED],
    ["done"]]}


class TwoDisputesOfOneFinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start(cls, ["fail", CONCEDE], rounds=2, fixer=FIXER, env=OWNERS)
        cls.home.write(".agentkit/state/boards.json", boards())
        cls.models = cls.home.ak("models", "--json", env=ENV)

    def test_both_accepted_disputes_reach_the_review_and_result_together(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.state["verdict"], "PASS")
        prompt = Path(self.fakes["codex"].runs()[1]["argv"][3]).read_text()
        for text in (f"Dispute: {FIRST}", "first proof output", f"Dispute: {SECOND}", "Quote:\n  hello"):
            self.assertIn(text, prompt)
            self.assertIn(text, self.result)
        self.assertTrue((self.run_dir / "round-2/dispute-1.log").is_file())
        self.assertEqual(len(self.state["disputes"]), 1)

    def test_history_and_models_ledger_count_the_disputed_finding_once(self):
        self.assertEqual(
            read(self.home, "SELECT path, line, proof, commit_exit, outcome, reason "
                            "FROM findings WHERE kind='dispute'"),
            [{"path": "retry.txt", "line": 1, "proof": "echo first proof output",
              "commit_exit": 0, "outcome": "conceded", "reason": CONCEDED}])
        self.assertEqual(self.models.code, 0, self.models.out + self.models.err)
        team, = json.loads(self.models.out)["runs"]["teams"]
        self.assertEqual({key: team[key] for key in ("issues", "disputed", "taken_back")},
                         {"issues": 1, "disputed": 1, "taken_back": 1})


if __name__ == "__main__":
    unittest.main()

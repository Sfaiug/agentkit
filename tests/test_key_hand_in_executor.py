"""A turn closes once, by the words its role may use: done, blocked or not-needed for work.

An executor or fixer ends with `ak hand-in done`, `blocked "why"` or `not-needed "why"`; a
review turn ends only with done, and only it hands in findings and follow-ups; only a fixer
disputes.  The first closing record is the turn's verdict, so every record after it is
refused, and each refusal exits 2 with one line saying what is allowed.  The loop reads these
rows to decide a round, so a wrong role's word must never land in hand-in.jsonl.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, `ak worker
--role` starting each turn and the scripted adapter of fakeadapter.py handing in from inside
it, as a model does from the worker's shell.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

ONLY_REVIEW = "ak hand-in: finding and follow-up are only for review turns\n"
ONLY_WORK = "ak hand-in: blocked and not-needed are only for executor or fixer turns\n"
ONLY_FIXER = "ak hand-in: dispute is only for fixer turns\n"
ONE_WHY = 'ak hand-in: use blocked or not-needed with one nonempty "why"\n'
CLOSED = ("ak hand-in: this turn is already closed; hand in records before done, blocked or "
          "not-needed\n")
FINDING = ["finding", "api.py:1", "Wrong result", "Breaks callers", "--quote", "return None"]
DISPUTE = ["dispute", "api.py:1", "not a defect", "--quote", "return None"]
REVIEWS = ("reviewer", "reviewer-pr", "reviewer-scratch")
WORK = ("executor", "fixer", "executor-scratch", "fixer-scratch")


class HandInByRole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"beta": "codex"})
        cls.fake = fakeadapter.install(cls.home, codex="pass")["codex"]
        # A real site and a verbatim quote: each refusal is about the role, not the evidence.
        cls.workspace = cls.home.path / "code" / "fix-api"
        cls.workspace.mkdir(parents=True)
        (cls.workspace / "api.py").write_text("def get():\n    return None\n")
        cls.task = cls.home.write("tasks/fix-api.md", "Fix the api.\n")
        cls.turns = 0

    def turn(self, role, *hand_ins):
        """Each hand-in's exit code and stderr, and the records the turn's file kept."""
        type(self).turns += 1
        out = self.home.root / "out" / f"{self.turns}-{role}"
        self.fake.behave({"hand_in": [list(argv) for argv in hand_ins], "final": "Handed in."})
        done = self.home.ak("worker", "beta", str(self.task), "--workspace",
                            str(self.workspace), "--out", str(out), "--role", role)
        self.assertEqual(done.code, 0, done.err)
        said = [(row["code"], row["err"]) for row in self.fake.runs()[-1]["hand_ins"]]
        rows = [json.loads(line) for line in (out / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual((rows[0]["kind"], rows[0]["role"]), ("turn", role))
        return said, rows[1:]

    def test_an_executor_is_refused_a_finding_and_closes_its_turn_with_done_once(self):
        said, rows = self.turn("executor", FINDING, ["done"], ["done"])
        self.assertEqual(said, [(2, ONLY_REVIEW), (0, ""), (2, CLOSED)])
        self.assertEqual(rows, [{"kind": "done"}])

    def test_an_executor_hands_in_not_needed_with_its_one_reason_and_nothing_after(self):
        said, rows = self.turn(
            "executor", ["follow-up", *FINDING[1:]], DISPUTE, ["blocked", ""],
            ["blocked", "  "], ["not-needed", "already", "fixed"], ["blocked"],
            ["not-needed", "already fixed upstream"], ["done"], ["blocked", "too late"])
        self.assertEqual(said, [(2, ONLY_REVIEW), (2, ONLY_FIXER), (2, ONE_WHY), (2, ONE_WHY),
                                (2, ONE_WHY), (2, ONE_WHY), (0, ""), (2, CLOSED), (2, CLOSED)])
        self.assertEqual(rows, [{"kind": "not-needed", "why": "already fixed upstream"}])

    def test_a_fixer_hands_in_blocked_with_its_reason_trimmed(self):
        said, rows = self.turn("fixer", FINDING, ["blocked", "  the api needs the owner \n"],
                               ["not-needed", "already fixed upstream"])
        self.assertEqual(said, [(2, ONLY_REVIEW), (0, ""), (2, CLOSED)])
        self.assertEqual(rows, [{"kind": "blocked", "why": "the api needs the owner"}])

    def test_a_reviewer_is_refused_blocked_not_needed_and_dispute_and_closes_with_done(self):
        said, rows = self.turn("reviewer", ["blocked", "no access"],
                               ["not-needed", "already fixed upstream"], DISPUTE, ["done"],
                               ["done"], FINDING)
        self.assertEqual(said, [(2, ONLY_WORK), (2, ONLY_WORK), (2, ONLY_FIXER), (0, ""),
                                (2, CLOSED), (2, CLOSED)])
        self.assertEqual(rows, [{"kind": "done"}])

    def test_every_role_closes_by_its_own_words(self):
        for role in REVIEWS + WORK:
            with self.subTest(role):
                said, rows = self.turn(role, ["blocked", "no access"], ["done"])
                if role in REVIEWS:
                    self.assertEqual((said, rows), ([(2, ONLY_WORK), (0, "")], [{"kind": "done"}]))
                else:
                    self.assertEqual((said, rows), ([(0, ""), (2, CLOSED)],
                                                    [{"kind": "blocked", "why": "no access"}]))


if __name__ == "__main__":
    unittest.main()

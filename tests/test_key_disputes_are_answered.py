"""AK_BIN refuses a review's done until each handed dispute has an explicit answer."""

import json
from pathlib import Path
import unittest

from test_key_fixer_dispute_run import FIXER, start
from test_key_history_db import OWNERS, read

WHY = "The task requires this file."
# The changed hand-in usage belongs to this key; shared verbs keep their exact usage checks.
HAND_IN_USAGE = ('usage: ak hand-in finding PATH:LINE "WHAT" "WHY IT MATTERS" '
                 "(--run COMMAND | --quote LINES)\n"
                 '       ak hand-in follow-up PATH:LINE "WHAT" "WHY IT MATTERS" '
                 "(--run COMMAND | --quote LINES) [--before PROOF]\n"
                 '       ak hand-in dispute PATH:LINE "WHY IT IS WRONG" '
                 "(--run COMMAND | --quote LINES)\n"
                 '       ak hand-in concede PATH:LINE "WHY"\n'
                 "       ak hand-in done\n"
                 '       ak hand-in blocked "WHY"\n'
                 '       ak hand-in not-needed "WHY"')


class Conceded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start(cls, ["fail", {"final": "Answered.", "hand_in": [
            ["done"], ["concede", "retry.txt:2", WHY], ["concede", "retry.txt:1", " "],
            ["concede", "retry.txt:1", WHY], ["done"]]}], rounds=2, env=OWNERS)

    def test_silence_is_refused_and_the_refusal_names_the_site_and_both_answers(self):
        review = self.fakes["codex"].runs()[1]
        self.assertEqual([row["code"] for row in review["hand_ins"]], [2, 2, 2, 0, 0])
        error = review["hand_ins"][0]["err"]
        for text in ("retry.txt:1", "ak hand-in finding", "ak hand-in concede"):
            self.assertIn(text, error)
        rows = [json.loads(line) for line in
                (self.run_dir / "round-2/reviewer/hand-in.jsonl").read_text().splitlines()]
        self.assertEqual([row["kind"] for row in rows], ["turn", "concede", "done"])
        self.assertEqual(rows[1]["why"], WHY)

    def test_conceding_passes_and_keeps_why_beside_the_dispute_in_history(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.state["verdict"], "PASS")
        self.assertEqual(read(self.home,
            "SELECT path, line, outcome, reason FROM findings WHERE kind='dispute'"),
            [{"path": "retry.txt", "line": 1, "outcome": "conceded", "reason": WHY}])
        self.assertIn("Conceded: " + WHY, self.result)
        self.assertIn("Dispute: it is right", self.result)
        heads = [summary["head_sha"] for summary in self.state["round_summaries"]]
        self.assertEqual(heads[0], heads[1])
        prompt = Path(self.fakes["codex"].runs()[1]["argv"][3]).read_text()
        # the dispute is shown; how to answer it, done's refusal names (above)
        for text in ("Dispute: it is right", "hand it in again to uphold it", "ak hand-in finding"):
            self.assertIn(text, prompt)

    def test_concede_has_help_outside_a_worker_turn(self):
        for flag in ("-h", "--help"):
            helped = self.home.ak("hand-in", "concede", flag)
            self.assertEqual((helped.code, helped.err), (0, ""))
            self.assertIn('usage: ak hand-in concede PATH:LINE "WHY"', helped.out)
            helped = self.home.ak("hand-in", flag)
            self.assertEqual((helped.code, helped.err), (0, ""))
            self.assertEqual(helped.out.split("\n\n")[1], HAND_IN_USAGE)


class Upheld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start(cls, ["fail", "fail"], rounds=2, env=OWNERS)

    def test_handing_in_the_finding_again_answers_and_fails_the_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.state["verdict"], "FAIL")
        self.assertEqual([row["code"] for row in self.fakes["codex"].runs()[1]["hand_ins"]], [0, 0])
        self.assertEqual(read(self.home,
            "SELECT outcome FROM findings WHERE kind='dispute'"), [{"outcome": "upheld"}])


class ReplacedLine(Upheld):
    @classmethod
    def setUpClass(cls):
        fixer = {**FIXER, "write": {"retry.txt": "new one\nnew two\n"}}
        uphold = {"final": "Upheld at its replacement.", "hand_in": [
            ["finding", "retry.txt:2", "fixture defect", "the fixture says so", "--run",
             "test ! -f retry.txt"], ["done"]]}
        start(cls, ["fail", uphold], rounds=2, fixer=fixer, env=OWNERS)


if __name__ == "__main__":
    unittest.main()

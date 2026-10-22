"""A worker turn that ends without its closing hand-in is asked once more, in its own session.

A model that stops talking before `ak hand-in done` has not answered, and taking its silence as
an answer would either throw away finished work or pass a change nobody judged.  So ak asks the
same conversation once, in the same round: an executor silent twice has its work go on to the
checks and review as if done, and a reviewer silent twice is gone, so the review goes to the next
model.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
on a project from gitrig.py, a config from akconfig.py, a task from taskfile.py and scripted
harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# The work committed and summed up, and no closing handed in.
NO_CLOSING = {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt",
              "final": "## Summary\nwrote retry.txt"}
CLOSING_ASK = "Your previous turn ended without a closing hand-in."
VERDICT_ASK = "Your previous turn ended without ak hand-in done."
CLOSINGS = ("done", "blocked", "not-needed")


class Silence:
    """One --no-merge run of opus executing and astra reviewing, scripted by `steps`."""
    steps = {}

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, **cls.steps)
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.log = (cls.run_dir / "log.txt").read_text()

    def turns(self, harness):
        """Each turn the harness ran: its prompt's text, its out directory and the session it
        was told to resume, if any."""
        found = []
        for call in self.fakes[harness].runs():
            _model, _effort, _workspace, prompt, out, *session = call["argv"]
            found.append((Path(prompt).read_text(), Path(out), session[0] if session else None))
        return found

    def assert_passed_in_one_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        # The ask is part of the round it was made in, never a round of its own.
        self.assertEqual([row["verdict"] for row in self.state["round_summaries"]], ["PASS"])
        self.assertIn("rounds: 1 of 3", (self.run_dir / "result.md").read_text().splitlines())


class SilentExecutor(Silence, unittest.TestCase):
    steps = {"claude": NO_CLOSING, "codex": "pass"}

    def test_an_executor_without_a_closing_is_asked_once_more_in_the_same_conversation(self):
        self.assertEqual(self.log.count("executor opus gave no closing; asking once more"), 1,
                         self.log)
        self.assertEqual(self.fakes["claude"].n, 2)
        (first, first_out, first_session), (ask, _, ask_session) = self.turns("claude")
        self.assertIsNone(first_session)
        self.assertEqual(ask_session, (first_out / "session_id").read_text().strip())
        self.assertNotIn(CLOSING_ASK, first)
        self.assertIn(CLOSING_ASK, ask)

    def test_the_ask_writes_beside_the_first_turn_and_keeps_its_record(self):
        (_, first_out, _), (_, ask_out, _) = self.turns("claude")
        self.assertEqual(first_out, self.run_dir / "round-1/executor")
        self.assertEqual(ask_out.parent, self.run_dir / "round-1")
        self.assertNotEqual(ask_out, first_out)
        self.assertEqual((first_out / "final.md").read_text(), "## Summary\nwrote retry.txt\n")

    def test_a_second_silence_goes_on_to_the_checks_and_review_as_if_done(self):
        self.assert_passed_in_one_round()
        self.assertEqual(self.fakes["codex"].n, 1)
        self.assertTrue(self.state["round_summaries"][0]["done_when"])
        for record in sorted(self.run_dir.glob("round-1/executor*/hand-in.jsonl")):
            with self.subTest(record.parent.name):
                rows = [json.loads(line) for line in record.read_text().splitlines()]
                self.assertFalse([row for row in rows if row.get("kind") in CLOSINGS])
        tree = self.home.run("git", "-C", self.state["worktree"], "ls-tree", "--name-only",
                             "HEAD")
        self.assertIn("retry.txt", tree.out.split())

    def test_result_md_keeps_the_summary_the_silent_turn_wrote(self):
        self.assertIn("wrote retry.txt", (self.run_dir / "result.md").read_text())


class SilentReviewer(Silence, unittest.TestCase):
    steps = {"claude": "work", "codex": ["silent", "pass"]}

    def test_a_reviewer_without_a_verdict_is_asked_once_more_in_the_same_conversation(self):
        self.assertEqual(self.log.count("reviewer astra gave no verdict; asking once more"), 1,
                         self.log)
        self.assertEqual(self.fakes["codex"].n, 2)
        (first, first_out, first_session), (ask, _, ask_session) = self.turns("codex")
        self.assertIsNone(first_session)
        self.assertEqual(ask_session, (first_out / "session_id").read_text().strip())
        self.assertNotIn(VERDICT_ASK, first)
        self.assertIn(VERDICT_ASK, ask)

    def test_the_ask_runs_in_a_fresh_attempt_folder_beside_the_first(self):
        (_, first_out, _), (_, ask_out, _) = self.turns("codex")
        self.assertEqual(first_out, self.run_dir / "round-1/reviewer")
        self.assertEqual(ask_out, self.run_dir / "round-1/reviewer-attempt2")
        self.assertTrue(first_out.is_dir())
        self.assertTrue(ask_out.is_dir())

    def test_the_answer_to_the_ask_is_the_round_s_verdict(self):
        self.assert_passed_in_one_round()
        self.assertEqual((self.state["executor"], self.state["reviewer"]), ("opus", "astra"))
        self.assertEqual(self.fakes["claude"].n, 1)
        rows = [json.loads(line) for line in
                (self.run_dir / "round-1/reviewer-attempt2/hand-in.jsonl").read_text()
                .splitlines()]
        self.assertEqual(rows[-1], {"kind": "done"})


class ReviewerSilentTwice(Silence, unittest.TestCase):
    # Words but no verdict, both times: the ask is answered, just not with a hand-in.
    steps = {"claude": "work", "codex": {"final": "Looks fine."}}

    def test_a_reviewer_silent_twice_is_asked_no_third_time(self):
        self.assertEqual(self.log.count("reviewer astra gave no verdict; asking once more"), 1,
                         self.log)
        self.assertEqual(self.fakes["codex"].n, 2)
        self.assertEqual([call["role"] for call in self.fakes["codex"].runs()],
                         ["reviewer", "reviewer"])

    def test_the_review_goes_to_the_next_model_and_its_verdict_decides(self):
        self.assert_passed_in_one_round()
        # No other model is left, so the executor's own reviews rather than none.
        self.assertEqual([call["role"] for call in self.fakes["claude"].runs()],
                         ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["reviewer"]), ("opus", "opus"))
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertIn("executor: opus   reviewer: opus",
                      (self.run_dir / "result.md").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()

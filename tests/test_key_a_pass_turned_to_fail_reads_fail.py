"""A PASS ak turned to FAIL reads FAIL in the review's text.

Where ak fails what its reviewer passed, the review it writes from the reviewer's records has
`VERDICT: FAIL` as its verdict line: the findings a task run records when done-when fails, and
what is posted on a seat's own pull request whose chosen tests are red, its "## Overridden to
FAIL" saying why.  The reviewer's own answer is kept as written.  A review that fails by its
reviewer's own verdict, and one that passes, read as their reviewer gave them.

Why: a fixer, or the author of a pull request, would read a failed review whose own text says PASS.

Black-box, on the fixtures of tests/test_key_a_seats_own_pull_request_runs_the_quick_set.py: the
program `AK_BIN` names runs four jobs in one Home.  A first seat PR lands to create history.db;
then earlier landings red on often.sh and the time record are written, and a seat's own PR whose
first review fails and second passes runs, then one whose change breaks often.sh, its reviewer
passing it twice, and last a one-round task run whose reviewer answers PASS while done-when fails.
"""

import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_reviewers_pass_runs_the_quick_set import OFTEN, review
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_a_round_runs_the_tests_that_fail_most_at_landing import DAY, NOW
from test_key_a_seats_own_pull_request_runs_the_quick_set import RUNS, TIMES

ANSWER = "VERDICT: PASS\nNothing to find."
OVERRIDDEN = "## Overridden to FAIL"


def verdicts(text):
    return [line for line in text.splitlines() if line.startswith("VERDICT:")]


class PassTurnedToFailReadsFail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        clock.standing(cls.home, "AK_ROUND_CLOCK", NOW)
        said = Notes()
        cls.addClassCleanup(said.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nusers: none\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=said.address), "widget.txt": "v1\n",
            "tests/often.sh": OFTEN, "tests/other.sh": "true\n"})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
        # claude: fixer for fixed, fixer for broken, executor for the task run.
        # codex: reviewer for seed, fixed (FAIL then PASS), broken (PASS then PASS), the task run.
        cls.fakes = fakeadapter.install(cls.home, claude=[
            {"write": {"fixed.txt": "good\n"}, "commit": "fixed good",
             "final": "## Summary\ngood", "hand_in": [["done"]]},
            {"write": {"widget.txt": "v1\n"}, "commit": "widget v1",
             "final": "## Summary\nwidget v1", "hand_in": [["done"]]},
            {"write": {"other.txt": "hello\n"}, "commit": "add other.txt",
             "final": "## Summary\nwrote other.txt", "hand_in": [["done"]]},
        ], codex=[
            review(said),
            review(said, "fixed.txt"), review(said),
            review(said), review(said),
            {"final": ANSWER, "hand_in": [["done"]]},
        ])
        cls.prs = {}

        def review_pr(name, files):
            cls.rig.git("checkout", "-q", "main")
            cls.rig.git("pull", "-q", "--ff-only")
            cls.rig.branch(name, files)
            url = cls.gh.open_pr(cls.rig, name, title=f"Add {name}", author="acme")
            done = cls.home.ak("run", "--review-pr", url, env={"AGENTKIT_SESSION": "acme"},
                               cwd=cls.rig.path, timeout=300)
            assert done.code == 0, done.out + done.err
            cls.prs[name] = cls.gh.pr(int(url.rsplit("/", 1)[1]))

        # First seat PR lands with no time record or reds yet, leaving ak's history.db in place.
        review_pr("seed", {"seed.txt": "0\n"})
        cls.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
        with sqlite3.connect(cls.home.path / ".agentkit/history.db") as connection:
            connection.executemany(
                "INSERT INTO runs (run_id, repo, final_state, started_at, finished_at) "
                "VALUES (?, 'widgets', 'pass', ?, ?)",
                [(run, NOW - DAY, NOW - DAY) for run in RUNS])
            connection.executemany(
                "INSERT INTO test_reds (run_id, round, kind, tree, test, flaky, at) "
                "VALUES (?, NULL, 'landing', 'tree', './tests/often.sh', 0, ?)",
                [(run, NOW - DAY) for run in RUNS])
        review_pr("fixed", {"fixed.txt": "bad\n"})
        review_pr("broken", {"broken.txt": "2\n", "widget.txt": "v2\n"})

        cls.rig.git("checkout", "-q", "main")
        cls.rig.git("pull", "-q", "--ff-only")
        before = set(taskfile.runs(cls.home))
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file", front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), cwd=cls.rig.path, timeout=300)
        (cls.run_dir,) = set(taskfile.runs(cls.home)) - before
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def posted(self, name):
        return [review["body"] for review in self.prs[name]["reviews"]]

    def test_a_task_runs_pass_turned_by_failing_done_when_records_fail_and_keeps_the_answer(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["verdict"], self.state["review"]["done_when"]), ("FAIL", False))
        self.assertTrue(self.state["review"]["overridden"].startswith(
            "the reviewer said PASS while done-when is failing"), self.state["review"])
        self.assertEqual(self.state["findings"], "VERDICT: FAIL")
        self.assertEqual(Path(self.state["findings_file"]).read_text(), "VERDICT: FAIL\n")
        self.assertEqual((self.run_dir / "round-1/reviewer/final.md").read_text(), ANSWER + "\n")

    def test_a_seats_own_pr_whose_chosen_tests_are_red_after_a_pass_posts_fail(self):
        turned, passed = self.posted("broken")
        self.assertIn(OVERRIDDEN, turned.splitlines())
        self.assertEqual(verdicts(turned), ["VERDICT: FAIL"])
        self.assertEqual(verdicts(passed), ["VERDICT: PASS"])

    def test_a_review_failed_by_its_reviewer_and_one_passed_read_as_given(self):
        failed, passed = self.posted("fixed")
        (seeded,) = self.posted("seed")
        self.assertEqual([verdicts(body) for body in (failed, passed, seeded)],
                         [["VERDICT: FAIL"], ["VERDICT: PASS"], ["VERDICT: PASS"]])
        self.assertIn("## Findings", failed.splitlines())
        self.assertFalse([body for body in (failed, passed, seeded)
                          if OVERRIDDEN in body.splitlines()])


if __name__ == "__main__":
    unittest.main()

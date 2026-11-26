"""Another author's pull request runs the whole `tests:` line only behind its reviewer's PASS.

Nothing of `tests:` runs before the review: a PR whose review passes runs the whole line after
the review was asked for, with no test named, and records it as passed; one whose review fails
runs nothing; and one that breaks a test while its reviewer answers PASS ends FAIL with the
first failing line and is not offered for merge.

Owner, 20 and 22 Nov 2026: "Once, after review passes" / "Yes, change it"; 26 Nov:
"Keep as built" (the comment at `roundloop._review`).

Black-box, on the fixtures of tests/test_key_a_seats_own_pull_request_runs_the_quick_set.py:
the program `AK_BIN` names runs three reviews of another author's pull requests in one Home,
against the bare origin of gitrig.py, the GitHub of fakegh.py and scripted reviewers from
fakeadapter.py, with the suite and reviewers noting each start on notes.py.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_reviewers_pass_runs_the_quick_set import OFTEN, review
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_a_round_runs_the_tests_that_fail_most_at_landing import SAID
from test_key_a_seats_own_pull_request_runs_the_quick_set import TIMES


class AnothersPrSuiteAfterReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        said = Notes()
        cls.addClassCleanup(said.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nusers: none\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=said.address), "widget.txt": "v1\n",
            "tests/often.sh": OFTEN, "tests/other.sh": "true\n"})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        # Even with a time record in place, another author's PR runs the whole line, no test named.
        cls.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus"])
        cls.inbox = Seat(cls.home, "inbox", cwd=cls.rig.path) if REAL_TMUX else None
        cls.fakes = fakeadapter.install(cls.home, claude=[
            review(said),
            review(said, "bad.txt"),
            review(said),
        ])
        cls.done, cls.notes, cls.states, cls.prs = {}, {}, {}, {}

        def review_pr(name, files):
            cls.rig.git("checkout", "-q", "main")
            head = cls.rig.branch(name, files)
            url = cls.gh.open_pr(cls.rig, name, title=f"Add {name}", author="other-dev")
            number = int(url.rsplit("/", 1)[1])
            before = set(taskfile.runs(cls.home))
            cls.done[name] = cls.home.ak("run", "--review-pr", url, cwd=cls.rig.path, timeout=300)
            cls.notes[name] = said.since()
            (run_dir,) = set(taskfile.runs(cls.home)) - before
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))
            cls.prs[name] = (number, url, head)

        review_pr("passed", {"passed.txt": "ok\n", "tests/often.sh": f"# passed\n{OFTEN}"})
        review_pr("failed", {"bad.txt": "bad\n", "tests/often.sh": f"# failed\n{OFTEN}"})
        review_pr("broken", {"broken.txt": "2\n", "widget.txt": "v2\n"})

    def test_a_passing_review_runs_the_whole_suite_after_review_and_records_pass(self):
        done, (run_dir, state) = self.done["passed"], self.states["passed"]
        number, url, head = self.prs["passed"]
        notes = self.notes["passed"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "own_pr",
                                                          "review_posted")},
                         {"state": "pass", "verdict": "PASS", "own_pr": False,
                          "review_posted": True})
        self.assertEqual(notes[0], "review", notes)
        self.assertTrue(notes[1:] and set(notes[1:]) == {"suite whole"}, notes)
        self.assertIs(state["review"]["done_when"], True)
        self.assertIs(state["round_summaries"][0]["done_when"], True)
        self.assertIn("## Round 1 (PASS, done-when passed)", (run_dir / "result.md").read_text())
        dw = (run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ python3 suite.py", dw)
        self.assertIn("[exit 0]", dw)
        prompt = Path(self.fakes["claude"].runs()[0]["argv"][3]).read_text()
        self.assertIn("nothing was run before this review", prompt)
        self.assertIn("by design", prompt)
        (posted,) = self.gh.pr(number)["reviews"]
        self.assertEqual((posted["state"], posted["commit"]["oid"]), ("COMMENTED", head))
        self.assertIn("VERDICT: PASS", posted["body"].splitlines())
        if self.inbox is not None:
            line = self.inbox.wait_lines(1)[0]
            self.assertIn(url, line)
            self.assertIn(f"--match-head-commit {head}", line)

    def test_a_failing_review_runs_nothing(self):
        done, (run_dir, state) = self.done["failed"], self.states["failed"]
        number, _, head = self.prs["failed"]
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "own_pr",
                                                          "review_posted")},
                         {"state": "fail", "verdict": "FAIL", "own_pr": False,
                          "review_posted": True})
        self.assertEqual(self.notes["failed"], ["review"])
        self.assertIsNone(state["review"]["done_when"])
        self.assertIsNone(state["round_summaries"][0]["done_when"])
        self.assertFalse((run_dir / "round-1/donewhen.log").exists())
        self.assertIn("## Round 1 (FAIL, done-when not run)", (run_dir / "result.md").read_text())
        self.assertIsNone(state.get("merge_note"))
        self.assertIsNone(state.get("pending_inbox"))
        (posted,) = self.gh.pr(number)["reviews"]
        self.assertEqual((posted["state"], posted["commit"]["oid"]), ("CHANGES_REQUESTED", head))

    def test_a_pass_whose_suite_fails_ends_fail_with_the_first_failing_line_and_is_not_offered(self):
        done, (run_dir, state) = self.done["broken"], self.states["broken"]
        number, url, head = self.prs["broken"]
        notes = self.notes["broken"]
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "own_pr",
                                                          "review_posted")},
                         {"state": "fail", "verdict": "FAIL", "own_pr": False,
                          "review_posted": True})
        self.assertEqual(notes[0], "review", notes)
        self.assertTrue(notes[1:] and set(notes[1:]) == {"suite whole"}, notes)
        self.assertIs(state["review"]["done_when"], False)
        self.assertIs(state["round_summaries"][0]["done_when"], False)
        self.assertIn(SAID, state["review"]["overridden"])
        result = (run_dir / "result.md").read_text()
        self.assertIn("## Round 1 (FAIL, done-when failed)", result)
        self.assertIn("## Overridden to FAIL", result)
        self.assertIn(SAID, result)
        dw = (run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ python3 suite.py", dw)
        self.assertIn(SAID, dw)
        (posted,) = self.gh.pr(number)["reviews"]
        self.assertEqual((posted["state"], posted["commit"]["oid"]), ("CHANGES_REQUESTED", head))
        self.assertIn("## Overridden to FAIL", posted["body"])
        self.assertIn(SAID, posted["body"])
        self.assertIn("VERDICT: FAIL", posted["body"].splitlines())
        self.assertIsNone(state.get("merge_note"))
        self.assertIsNone(state.get("pending_inbox"))
        if self.inbox is not None:
            self.assertEqual([line for line in self.inbox.lines() if url in line], [])


if __name__ == "__main__":
    unittest.main()

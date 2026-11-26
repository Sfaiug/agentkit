"""A seat's own pull request runs the quick set once its reviewer answers PASS.

With a time record and landings red on a test, the review of a seat's own pull request hands the
suite that test once its reviewer has answered PASS, not before and not after a failed review.  A
commit that breaks that test turns the review's verdict to FAIL, does not merge on that commit,
and hands the seat's fixer the first failing line with the findings; the fixer's commit passes the
test and merges.  A review of another author's pull request hands the suite nothing.  A task run
with `--no-worktree` hands the suite that test once its reviewer has answered PASS, but nothing on
a target only the local repository has.

Owner, 20 Nov 2026: "why does an orch never get a quick set?".

Black-box, on the fixtures of tests/test_key_a_reviewers_pass_runs_the_quick_set.py and
tests/test_key_own_pr_fix_and_land.py: the program `AK_BIN` names runs five jobs in one Home,
against the bare origin of gitrig.py, the GitHub of fakegh.py, the seat of akseat.py and scripted
harnesses from fakeadapter.py, its clock injected (tests/fixtures/clock.py).  A first seat PR lands
to create history.db; then earlier landings red on often.sh and the time record are written, and
five jobs run: a seat's own PR whose first review fails and second passes; a seat's own PR whose
change breaks often.sh; another author's PR; and two `--no-worktree` task runs, the second on a
branch origin has none of.
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
from test_key_a_reviewers_pass_runs_the_quick_set import CHOSEN, OFTEN, review
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_a_round_runs_the_tests_that_fail_most_at_landing import DAY, NOW, SAID

RUNS = ("fix-a", "fix-b", "fix-c")
TIMES = {"./tests/often.sh": 1, "./tests/other.sh": 1}


class SeatOwnPrQuickSet(unittest.TestCase):
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
             record={"workers": ["opus", "astra"]}, planned=("test -f local.txt", "test -f draft.txt"))
        # claude: fixer for fixed, fixer for broken, reviewer for other (no writer -> first model),
        # executor for each --no-worktree run.
        # codex: reviewer for seed, fixed (FAIL then PASS), broken (PASS then PASS), each
        # --no-worktree run.
        cls.fakes = fakeadapter.install(cls.home, claude=[
            {"write": {"fixed.txt": "good\n"}, "commit": "fixed good",
             "final": "## Summary\ngood", "hand_in": [["done"]]},
            {"write": {"widget.txt": "v1\n"}, "commit": "widget v1",
             "final": "## Summary\nwidget v1", "hand_in": [["done"]]},
            review(said),
            {"write": {"local.txt": "l\n", "tests/often.sh": f"# local\n{OFTEN}"},
             "commit": "local", "final": "## Summary\nlocal", "hand_in": [["done"]]},
            {"write": {"draft.txt": "d\n", "tests/often.sh": f"# draft\n{OFTEN}"},
             "commit": "draft", "final": "## Summary\ndraft", "hand_in": [["done"]]},
        ], codex=[
            review(said),
            review(said, "fixed.txt"), review(said),
            review(said), review(said),
            review(said), review(said),
        ])
        cls.done, cls.notes, cls.states, cls.prs = {}, {}, {}, {}

        def review_pr(name, files, *, author="acme"):
            cls.rig.git("checkout", "-q", "main")
            cls.rig.git("pull", "-q", "--ff-only")
            head = cls.rig.branch(name, files)
            url = cls.gh.open_pr(cls.rig, name, title=f"Add {name}", author=author)
            number = int(url.rsplit("/", 1)[1])
            before = set(taskfile.runs(cls.home))
            cls.done[name] = cls.home.ak("run", "--review-pr", url,
                                         env={"AGENTKIT_SESSION": "acme"},
                                         cwd=cls.rig.path, timeout=300)
            cls.notes[name] = said.since()
            (run_dir,) = set(taskfile.runs(cls.home)) - before
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))
            cls.prs[name] = (number, head)

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
        review_pr("other", {"other.txt": "o\n", "tests/often.sh": f"# other\n{OFTEN}"},
                  author="other-dev")

        def no_worktree(name, front=None):
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}", front=front,
                                  done_when=(f"test -f {name}.txt",))
            before = set(taskfile.runs(cls.home))
            cls.done[name] = cls.home.ak("run", str(task), "--no-worktree", "--no-merge",
                                         env={"AGENTKIT_SESSION": "acme"},
                                         cwd=cls.rig.path, timeout=300)
            cls.notes[name] = said.since()
            (run_dir,) = set(taskfile.runs(cls.home)) - before
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

        cls.rig.git("checkout", "-q", "main")
        cls.rig.git("pull", "-q", "--ff-only")
        cls.rig.git("checkout", "-qb", "local")
        no_worktree("local")
        cls.rig.git("branch", "draft")
        no_worktree("draft", {"base": "draft"})

    def verdicts(self, name):
        return [summary["verdict"] for summary in self.states[name][1]["round_summaries"]]

    def test_a_seats_own_pr_hands_the_red_test_only_after_reviewer_pass(self):
        done, (_, state) = self.done["fixed"], self.states["fixed"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "merged", "own_pr")},
                         {"state": "pass", "verdict": "PASS", "merged": True, "own_pr": True})
        self.assertEqual(self.verdicts("fixed"), ["FAIL", "PASS"])
        self.assertEqual(self.notes["fixed"], ["review", "review", CHOSEN, "suite whole"])

    def test_a_seats_own_pr_breaking_the_test_does_not_merge_that_commit_and_tells_its_fixer(self):
        done, (_, state) = self.done["broken"], self.states["broken"]
        number, broken_head = self.prs["broken"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "merged", "own_pr")},
                         {"state": "pass", "verdict": "PASS", "merged": True, "own_pr": True})
        self.assertEqual(self.verdicts("broken"), ["FAIL", "PASS"])
        self.assertEqual(self.notes["broken"],
                         ["review", CHOSEN, CHOSEN, "review", CHOSEN, "suite whole"])
        pr = self.gh.pr(number)
        fixed_head = pr["merge"]["head"]
        self.assertNotEqual(fixed_head, broken_head)
        parent = self.home.run("git", "-C", str(self.rig.bare), "rev-parse", f"{fixed_head}^")
        self.assertEqual(parent.out.strip(), broken_head)
        self.assertEqual([posted["commit"]["oid"] for posted in pr["reviews"]],
                         [broken_head, fixed_head])
        fixer = self.fakes["claude"].runs()[1]
        self.assertEqual(fixer["role"], "fixer")
        prompt = Path(fixer["argv"][3]).read_text()
        self.assertIn("## Overridden to FAIL", prompt)
        self.assertIn(SAID, prompt)
        self.assertEqual(self.rig.origin("show", "main:widget.txt"), "v1")

    def test_another_authors_pr_hands_the_suite_nothing(self):
        done, (_, state) = self.done["other"], self.states["other"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "own_pr",
                                                          "review_posted")},
                         {"state": "pass", "verdict": "PASS", "own_pr": False,
                          "review_posted": True})
        self.assertEqual(self.notes["other"], ["review", "suite whole"])

    def no_worktree_notes(self, name, target):
        done, (_, state) = self.done[name], self.states[name]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "worktree",
                                                          "branch", "target", "no_merge")},
                         {"state": "pass", "verdict": "PASS", "worktree": str(self.rig.path),
                          "branch": "local", "target": target, "no_merge": True})
        return self.notes[name]

    def test_a_no_worktree_task_run_still_hands_the_suite_its_chosen_test(self):
        self.assertEqual(self.no_worktree_notes("local", "origin/main"), ["review", CHOSEN])

    def test_a_no_worktree_task_run_on_a_target_only_the_local_repository_has_hands_nothing(self):
        self.assertEqual(self.no_worktree_notes("draft", "draft"), ["review"])


if __name__ == "__main__":
    unittest.main()

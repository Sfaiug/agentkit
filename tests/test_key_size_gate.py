"""A task's first review takes at most 300 added lines, a seat's own pull request under 50.

Big changes merged far less often, so a task's change reaches its first reviewer only up to 300
added lines, past them refused with `split it`, and a seat builds only what stays under 50,
from 50 told to write a task for a worker.  What counts is what a reviewer reads: deleted lines
never count, nor files the target marks generated, nor blocks moved unchanged (whitespace
aside) from lines the same change deletes.  A task's change past the ceiling ends the run
blocked before any reviewer turn, its work kept on its branch for the pieces; a seat's own pull
request from 50 lines is refused at launch.  A later review of the same change, after a fix, is
not held to it.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from
fakeadapter.py and, for pull requests, the GitHub of fakegh.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

TAIL = ("(generated files aside; deletions never count): a first review takes at most 300; "
        "split it")
# The table keeps its heading, so a change moving its rows out is never read as a rename.
HEADING = "# widget table\n# rows below\n"


def rows(count, word="new", *, start=0, indent=""):
    """Distinct lines, each holding enough letters that a block of them can read as moved."""
    return "".join(f"{indent}{word} row {k:04d} of the widget table\n"
                   for k in range(start, start + count))


def change(files, *, commit=True):
    """An executor or fixer turn writing `files`, committed unless told not to, then done."""
    step = {"write": files, "final": "## Summary\nwrote it", "hand_in": [["done"]]}
    return {**step, "commit": "the change"} if commit else step


# A finding the next turn can fix: its check fails while flaw.txt is there.
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "big.txt:1", "a flaw left in", "flaw.txt is there", "--run",
     "test ! -f flaw.txt"], ["done"]]}

# title: (the executor's turns, then the fixer's; the reviewer's; the task's check)
CASES = {
    "At the ceiling": ([change({"big.txt": rows(300)})], ["pass"], "test -f big.txt"),
    # Executors leave their work uncommitted; the branch the blocked run keeps must hold it.
    "Past the ceiling": ([change({"big.txt": rows(301)}, commit=False)], ["pass"],
                         "test -f big.txt"),
    "Move the table": ([change({"table.txt": HEADING,
                                "shelf.txt": rows(600, "old", indent="    ") + rows(10)})],
                       ["pass"], "test -f shelf.txt"),
    "Drop the table": ([change({"table.txt": HEADING, "notes.txt": rows(10)})], ["pass"],
                       "test -f notes.txt"),
    "Rebuild the bundle": ([change({"dist/app.js": rows(500, "built"), "notes.txt": rows(10)})],
                           ["pass"], "test -f notes.txt"),
    "Move half and grow": ([change({"table.txt": HEADING + rows(300, "old"),
                                    "shelf.txt": rows(300, "old", start=300, indent="\t")
                                    + rows(301)})], ["pass"], "test -f shelf.txt"),
    "Grow after review": ([change({"flaw.txt": "x\n", "big.txt": rows(299)}),
                           {"sh": "git rm -q flaw.txt", **change({"more.txt": rows(300)})}],
                          [FINDING, "pass"], "test -f big.txt"),
}


def reviews(fakes):
    """Reviewer turns every harness has taken so far."""
    return sum(run["role"] == "reviewer" for fake in fakes.values() for run in fake.runs())


class TaskChange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "table.txt": HEADING + rows(600, "old"), "dist/app.js": "built\n",
            ".gitattributes": "dist/*.js linguist-generated\n"})
        akconfig.write(cls.home, ["opus", "astra"])
        fakes = fakeadapter.install(cls.home, claude="pass", codex="pass")
        cls.runs = {}
        for title, (work, review, check) in CASES.items():
            fakes["claude"].behave(*work)
            fakes["codex"].behave(*review)
            task = taskfile.write(cls.home, cls.rig.path, title, done_when=(check,))
            before = reviews(fakes)
            done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
            run_dir, = [path for path in taskfile.runs(cls.home)
                        if path.name.endswith("-" + taskfile.slug(title))]
            cls.runs[title] = (done, run_dir, json.loads((run_dir / "run.json").read_text()),
                               reviews(fakes) - before)

    def reviewed(self, title, rounds=1):
        """The run ended PASS after `rounds` reviews, none of them refused for its size."""
        done, run_dir, state, reviewed = self.runs[title]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["verdict"], reviewed), ("pass", "PASS", rounds))

    def blocked(self, title, why):
        """The run ended blocked for its size, saying `why`, before any reviewer turn."""
        done, run_dir, state, reviewed = self.runs[title]
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual((state["state"], state["verdict"], reviewed), ("blocked", "BLOCKED", 0))
        self.assertIn(f"BLOCKED {why}\n", (run_dir / "log.txt").read_text())
        lines = (run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], f"# BLOCKED — {title}")
        for line in ("VERDICT: BLOCKED", "rounds: 0 of 3", "## Blocked", why):
            self.assertIn(line, lines)

    def test_three_hundred_added_lines_get_their_first_review(self):
        self.reviewed("At the ceiling")

    def test_one_line_more_ends_the_run_blocked_before_any_review(self):
        self.blocked("Past the ceiling", f"The change on ak/past-the-ceiling adds 301 lines {TAIL}")
        # refused straight after the build: no done-when check, no fixer turn
        self.assertNotRegex((self.runs["Past the ceiling"][1] / "log.txt").read_text(),
                            r"done-when: (all passed|FAILED)")

    def test_the_blocked_run_keeps_its_work_on_its_branch_for_the_pieces(self):
        branch = "ak/past-the-ceiling"
        self.assertEqual(self.runs["Past the ceiling"][2]["branch"], branch)
        self.assertIn(branch, self.rig.branches(remote=False))
        self.assertEqual(self.rig.git("show", f"{branch}:big.txt") + "\n", rows(301))
        self.assertEqual(self.rig.branches(), ["main"])

    def test_lines_moved_unchanged_whitespace_aside_are_not_counted(self):
        # 610 added lines, 600 of them the table's rows re-indented in another file
        self.reviewed("Move the table")

    def test_deleted_lines_and_generated_files_are_not_counted(self):
        for title in ("Drop the table", "Rebuild the bundle"):
            with self.subTest(title):
                self.reviewed(title)

    def test_a_refusal_says_how_many_of_its_lines_were_moved(self):
        # 601 added, 300 of them moved: 301 left to read
        self.blocked("Move half and grow",
                     "The change on ak/move-half-and-grow adds 601 lines, 300 of them moved "
                     f"unchanged from lines it deletes {TAIL}")

    def test_only_the_first_review_is_held_to_the_ceiling(self):
        # 300 lines reviewed first, then a fix adding 300 more is reviewed again
        self.reviewed("Grow after review", rounds=2)
        tree = self.home.run("git", "-C", self.runs["Grow after review"][2]["worktree"],
                             "ls-tree", "--name-only", "HEAD").out.split()
        self.assertTrue({"big.txt", "more.txt"} <= set(tree), tree)


class SeatPullRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.gh = GitHub(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        fakes = fakeadapter.install(cls.home, claude="pass", codex="pass")
        Seat(cls.home, "acme", model="opus", cwd=cls.rig.path, alive=False, planned=True)
        cls.reviews = {}
        for branch, count in (("big-change", 50), ("fit-change", 49)):
            cls.rig.branch(branch, {f"{branch}.txt": rows(count)})
            url = cls.gh.open_pr(cls.rig, branch, title=branch)
            before = reviews(fakes)
            # the seat's own shell: its pull request, by this host's GitHub login
            done = cls.home.ak("run", "--review-pr", url, "--no-merge", cwd=cls.rig.path,
                               env={"AGENTKIT_SESSION": "acme"}, timeout=300)
            run_dir, = [path for path in taskfile.runs(cls.home)
                        if path.name.endswith(f"-review-pr-widgets-{url.split('/')[-1]}")]
            cls.reviews[branch] = (done, run_dir, reviews(fakes) - before)

    def test_a_pull_request_of_50_lines_is_refused_at_launch_unreviewed(self):
        done, run_dir, reviewed = self.reviews["big-change"]
        why = ("PR #1 adds 50 lines (generated files and unchanged moves aside): too big for the "
               "seat, which builds under 50 added lines. Write it as a task and launch it; a "
               "worker builds it")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn(why, done.err)
        self.assertEqual(reviewed, 0)
        lines = (run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# FAIL — Review PR #1: big-change")
        self.assertIn(why, lines)
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["reviews"]), ("OPEN", []))

    def test_a_pull_request_of_49_lines_gets_its_review(self):
        done, run_dir, reviewed = self.reviews["fit-change"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(reviewed, 1)
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((state["verdict"], state["review_pr"]),
                         ("PASS", "https://github.com/acme/widgets/pull/2"))


if __name__ == "__main__":
    unittest.main()

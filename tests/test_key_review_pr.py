"""`ak run --review-pr URL` reviews somebody else's PR and posts the verdict back to GitHub.

A review of another author's PR has no executor: the reviewer alone judges the PR's head,
checked out for the run, after the repository's own `tests:` line ran on it, and the job is
the review on GitHub, on the very commit reviewed.  A PASS is a comment, and so is a FAIL on a
PR the posting account opened; a FAIL on anyone else's requests changes, findings in its body.
A verdict GitHub refused to take is one nobody can read, so that run ends in error, exit 2,
and no seat is asked to merge it.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with
a scripted reviewer from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\n---\n# widget\n"
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "contrib.txt:1", "contrib.txt holds one letter", "nothing reads it", "--run",
     "test ! -f contrib.txt"], ["done"]]}
FOUND = "- contrib.txt:1 - contrib.txt holds one letter - nothing reads it"


def reviewed(case, step, *, author="other-dev", refused=False):
    """Run one review of a PR adding contrib.txt, opened by `author`, the reviewer doing
    `step`; GitHub refuses the review's post when `refused`.  The viewer is `acme`."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    rig = Rig(case.home, "widget", files={"AGENTS.md": RULES})
    case.gh = GitHub(case.home)
    case.head = rig.branch("contrib", {"contrib.txt": "c\n"})
    case.url = case.gh.open_pr(rig, "contrib", title="Add contrib", body="adds a file",
                               author=author)
    case.number = int(case.url.rsplit("/", 1)[1])
    if refused:
        case.gh.reply(f"api repos/{rig.slug}/pulls/{case.number}/reviews",
                      err="HTTP 502: bad gateway\n", code=1)
    akconfig.write(case.home, ["opus"])
    fakeadapter.install(case.home, claude=step)
    case.done = case.home.ak("run", "--review-pr", case.url, timeout=300)
    case.run_dir = taskfile.only_run(case.home)
    case.state = json.loads((case.run_dir / "run.json").read_text())


def posted(case):
    """The one review GitHub holds on the PR."""
    reviews = case.gh.pr(case.number)["reviews"]
    case.assertEqual(len(reviews), 1, reviews)
    return reviews[0]


class PassingReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, "pass")

    def test_the_reviewer_alone_judges_the_pr_head_by_its_author(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertRegex(self.run_dir.name, rf"^\d{{8}}-\d{{4}}-review-pr-widget-{self.number}$")
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "executor", "reviewer", "review_pr", "review_posted",
            "head_sha", "own_pr")}, {
            "state": "pass", "verdict": "PASS", "executor": None, "reviewer": "opus",
            "review_pr": self.url, "review_posted": True, "head_sha": self.head,
            "own_pr": False})
        at = self.home.run("git", "-C", self.state["worktree"], "rev-parse", "HEAD")
        self.assertEqual(at.out.strip(), self.head)
        log = (self.run_dir / "log.txt").read_text().splitlines()
        said = "] reviewer=opus (no executor: this is a review of somebody else's PR)"
        self.assertTrue([line for line in log if line.endswith(said)], log)

    def test_the_repository_s_tests_line_ran_on_the_pr_head(self):
        checks = (self.run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ test -f contrib.txt", checks.splitlines())
        self.assertIn("[exit 0]", checks)

    def test_the_verdict_is_posted_once_as_a_comment_on_the_reviewed_commit(self):
        review = posted(self)
        self.assertEqual((review["state"], review["commit"]["oid"]), ("COMMENTED", self.head))
        lines = review["body"].splitlines()
        self.assertEqual(lines[0], f"agentkit review of {self.head[:12]} by opus "
                                   f"(run {self.run_dir.name})")
        self.assertIn("VERDICT: PASS", lines)


class FailingReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, FINDING)

    def test_a_fail_ends_the_run_fail_with_its_verdict_posted(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "executor", "review_posted", "head_sha", "own_pr")}, {
            "state": "fail", "verdict": "FAIL", "executor": None, "review_posted": True,
            "head_sha": self.head, "own_pr": False})

    def test_it_requests_changes_on_the_reviewed_commit_with_the_findings(self):
        review = posted(self)
        self.assertEqual((review["state"], review["commit"]["oid"]),
                         ("CHANGES_REQUESTED", self.head))
        lines = review["body"].splitlines()
        self.assertEqual(lines[0], f"agentkit review of {self.head[:12]} by opus "
                                   f"(run {self.run_dir.name})")
        for line in ("VERDICT: FAIL", "## Findings", FOUND):
            self.assertIn(line, lines)

    def test_a_fail_is_offered_to_no_seat(self):
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0,
                            self.home.tmux("list-sessions").out)


class FailingReviewOfTheViewersOwnPr(unittest.TestCase):
    # GitHub refuses a changes-requested review from the PR's own author, which would turn
    # the FAIL into an error.
    @classmethod
    def setUpClass(cls):
        reviewed(cls, FINDING, author="acme")

    def test_a_fail_on_a_pr_the_posting_account_opened_is_a_comment(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"], self.state["own_pr"],
                          self.state["review_posted"]), ("fail", "FAIL", False, True))
        review = posted(self)
        self.assertEqual((review["state"], review["commit"]["oid"]), ("COMMENTED", self.head))
        for line in ("VERDICT: FAIL", FOUND):
            self.assertIn(line, review["body"].splitlines())


class RefusedPost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, "pass", refused=True)

    def test_a_review_github_refused_ends_the_run_in_error_with_exit_2(self):
        self.assertEqual(self.done.code, 2, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "review_posted")}, {
            "state": "error", "verdict": "PASS", "review_posted": False})
        error = self.state["error"]
        self.assertTrue(error.startswith(f"the review was not posted to {self.url}"), error)
        self.assertIn("HTTP 502", error)
        self.assertEqual(self.gh.pr(self.number)["reviews"], [])

    def test_the_result_says_why_and_nothing_is_offered(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertIn("## Why this run stopped", lines)
        why = lines[lines.index("## Why this run stopped") + 1:]
        self.assertIn(self.state["error"], why)
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0,
                            self.home.tmux("list-sessions").out)


if __name__ == "__main__":
    unittest.main()

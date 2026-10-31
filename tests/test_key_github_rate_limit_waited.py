"""A run's GitHub call that meets a spent API allowance waits for GitHub's reset and asks again.

On 26 Oct 2026 the owner's hourly allowance ran out and a review that had passed ended in error,
unable to read its PR to post the verdict.  Now a run's gh call that fails asks `gh api
rate_limit`, which spends none of it, and when `core` or `graphql` has `remaining` 0 waits
until the reset, says so once in the run's log, and asks again.  A failure with both left fails
as before; the tick never waits for it, since its passes ask again next tick.  Black-box
against the GitHub of tests/fixtures/fakegh.py, with a scripted reviewer from fakeadapter.py.
GitHub names the reset as the run asks for it, and today's ak sleeps until then (there is no
seam to shorten it), so this file takes a little over a minute.  The wait is judged by when the
run asked GitHub again, never by when it ended: a run that asked early and sat out the rest
only after would end just as late.
"""

from datetime import datetime, timezone
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SPENT = "gh: API rate limit exceeded for user ID 1. (HTTP 403)\n"
RATE_LIMIT = ["api", "rate_limit"]
# Seconds after the run asks that its allowance comes back: past ak's least wait, a minute, by
# more than a slow host takes to start waiting, so the run waits for the reset, not that.
AFTER = 70


def allowance(core, graphql, after):
    """`gh api rate_limit`'s answer: each resource's calls left, both coming back `after` seconds
    after it is asked."""
    resources = {name: {"limit": 5000, "used": 5000 - left, "remaining": left, "reset": 0}
                 for name, left in (("core", core), ("graphql", graphql))}
    # GitHub's reset is a number, which fakegh's `{in N}` stands for unquoted
    return json.dumps({"resources": resources}).replace('"reset": 0', f'"reset": {{in {after}}}')


def record(run_dir):
    """run.json now, or {} while it is missing or being written."""
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


def reviewed(case, script):
    """A review run of another author's PR, the reviewer passing it, gh first answering what
    `script(slug, pr)` says (`GitHub.reply`'s words), `pr` the REST API's read of the PR;
    `waiting` is the run's record as it first carried a wait, `reset` the one GitHub named."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    rig = Rig(case.home, "widget")
    case.gh = GitHub(case.home)
    case.head = rig.branch("contrib", {"contrib.txt": "c\n"})
    case.url = case.gh.open_pr(rig, "contrib", title="Add contrib", author="other-dev")
    pr = case.home.run("gh", "api", f"repos/{rig.slug}/pulls/1").out
    akconfig.write(case.home, ["opus"])
    fakeadapter.install(case.home, claude="pass")
    for prefix, reply in script(rig.slug, pr):
        case.gh.reply(prefix, **reply)
    proc = case.home.spawn("run", "--review-pr", case.url)
    case.waiting, deadline = None, time.monotonic() + 300
    while proc.poll() is None and time.monotonic() < deadline:
        for run_dir in taskfile.runs(case.home):
            state = record(run_dir)
            if case.waiting is None and state.get("transient_wait"):
                case.waiting = state
        time.sleep(0.1)
    case.code = proc.poll()
    case.out = "".join(case.home.log(f"spawn-1.{kind}").read_text() for kind in ("out", "err"))
    run_dir = taskfile.only_run(case.home)
    case.state = record(run_dir)
    case.asked = case.gh.asked()
    case.reset = next((int(at) + AFTER for at, argv in case.asked if argv == RATE_LIMIT), None)
    case.log = (run_dir / "log.txt").read_text().splitlines()
    case.said = [line for line in case.log if "waiting for GitHub's API allowance" in line]


class SpentAllowance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the launch's read and the round's pass; the read before the post is refused, as on
        # 26 Oct
        reviewed(cls, lambda slug, pr: [
            ("api rate_limit", {"out": allowance(0, 4000, AFTER)}),
            (f"api repos/{slug}/pulls/1", {"out": pr, "times": 2}),
            (f"api repos/{slug}/pulls/1", {"err": SPENT, "code": 1, "times": 1})])

    def test_the_run_asks_github_again_only_after_the_reset_then_posts_its_verdict(self):
        self.assertEqual(self.code, 0, self.out)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "review_posted", "head_sha")}, {
            "state": "pass", "verdict": "PASS", "review_posted": True, "head_sha": self.head})
        reviews = self.gh.pr(1)["reviews"]
        self.assertEqual([(review["state"], review["commit"]["oid"]) for review in reviews],
                         [("COMMENTED", self.head)])
        asked = [argv for _at, argv in self.asked]
        self.assertIn(RATE_LIMIT, asked)
        again = self.asked[asked.index(RATE_LIMIT) + 1:]
        self.assertTrue(again, "the run never asked GitHub again")
        self.assertGreaterEqual(min(at for at, _argv in again), self.reset, again)

    def test_while_it_waits_its_record_says_whose_wait_it_is_and_until_the_reset(self):
        self.assertIsNotNone(self.waiting, "run.json never carried transient_wait")
        self.assertEqual(self.waiting["state"], "running")
        self.assertEqual(self.waiting["transient_wait"]["pid"], self.waiting["pid"])
        self.assertAlmostEqual(self.waiting["transient_wait"]["until"], self.reset, delta=5)

    def test_its_log_names_the_wait_once(self):
        until = datetime.fromtimestamp(self.reset, timezone.utc)
        self.assertEqual(len(self.said), 1, self.log)
        self.assertTrue(self.said[0].endswith(
            f"] waiting for GitHub's API allowance until {until:%H:%M} UTC"), self.said)


class AllowanceLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, lambda slug, _pr: [
            ("api rate_limit", {"out": allowance(4999, 4999, AFTER)}),
            (f"api repos/{slug}/pulls/1/reviews", {"err": SPENT, "code": 1})])

    def test_a_failure_with_calls_left_ends_the_run_as_before_with_no_wait(self):
        self.assertEqual(self.code, 2, self.out)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "review_posted")}, {
            "state": "error", "verdict": "PASS", "review_posted": False})
        self.assertIn("API rate limit exceeded", self.state["error"])
        self.assertIn(RATE_LIMIT, [argv for _at, argv in self.asked])
        self.assertEqual((self.waiting, self.said), (None, []))


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Tick(unittest.TestCase):
    def test_a_tick_meeting_a_spent_allowance_goes_on_without_waiting(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        gh = GitHub(home)
        # a tick waiting for it would outlast its bound
        gh.reply("api rate_limit", allowance(0, 0, 3600))
        gh.reply("", err=SPENT, code=1)
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(home.calls("gh"), "the tick never asked GitHub")


if __name__ == "__main__":
    unittest.main()

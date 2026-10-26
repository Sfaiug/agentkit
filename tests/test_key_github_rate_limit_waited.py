"""A run's GitHub call that meets a spent API allowance waits for GitHub's reset and asks again.

On 26 Oct 2026 the owner's hourly allowance ran out and a review that had passed ended in error,
unable to read its PR to post the verdict.  Now a run's gh call that fails asks `gh api
rate_limit`, which spends none of it, and when `core` or `graphql` has `remaining` 0 sleeps
until the reset, says so once in the run's log, and asks again.  A failure with both left fails
as before; the tick never waits for it, since its passes ask again next tick.  Black-box
against the GitHub of tests/fixtures/fakegh.py, with a scripted reviewer from fakeadapter.py;
the review run starts through a launcher that hands turns the test clock of
tests/fixtures/clock.py, so a wait is recorded, with the run's record as it stood, never slept.
"""

from datetime import datetime, timezone
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, REPO, Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SPENT = "gh: API rate limit exceeded for user ID 1. (HTTP 403)\n"
# Every `bin/ak` the run starts, its detached loop included, takes the test clock into its
# turns, writing each wait's end and the run's record down, one per line, in the file it names.
CLOCK = """
import json, sys, time
if sys.argv[:1] == [{ak!r}]:
    found = sys.path[:]
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import config, turns
    sys.path[:] = found

    def sleep(seconds):
        records = [json.loads(path.read_text()) for path in config.RUNS.glob("*/run.json")]
        with open({ends!r}, "a") as ends:
            ends.write(json.dumps([time.time() + seconds, records]) + "\\n")

    turns.time = Clock(sleep)
"""


def allowance(core, graphql, reset):
    """`gh api rate_limit`'s answer: each resource's calls left, both coming back at `reset`."""
    return json.dumps({"resources": {name: {"limit": 5000, "used": 5000 - left, "remaining": left,
                                            "reset": reset}
                                     for name, left in (("core", core), ("graphql", graphql))}})


def reviewed(case, script):
    """A review run of another author's PR, the reviewer passing it, gh first answering what
    `script(slug, reset, pr)` says (`GitHub.reply`'s words), `pr` the REST API's read of the
    PR, the reset an hour away on a minute."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    rig = Rig(case.home, "widget")
    case.gh = GitHub(case.home)
    case.head = rig.branch("contrib", {"contrib.txt": "c\n"})
    case.url = case.gh.open_pr(rig, "contrib", title="Add contrib", author="other-dev")
    case.reset = (int(time.time()) // 60 + 60) * 60
    pr = case.home.run("gh", "api", f"repos/{rig.slug}/pulls/1").out
    for prefix, reply in script(rig.slug, case.reset, pr):
        case.gh.reply(prefix, **reply)
    akconfig.write(case.home, ["opus"])
    fakeadapter.install(case.home, claude="pass")
    site, ends = case.home.root / "clock", case.home.root / "waits.jsonl"
    site.mkdir()
    (site / "sitecustomize.py").write_text(CLOCK.format(
        ak=AK, repo=str(REPO), tests=str(REPO / "tests"), ends=str(ends)))
    ends.touch()
    case.done = case.home.ak("run", "--review-pr", case.url, env={"PYTHONPATH": str(site)},
                             timeout=300)
    case.run_dir = taskfile.only_run(case.home)
    case.state = json.loads((case.run_dir / "run.json").read_text())
    case.waits = [json.loads(line) for line in ends.read_text().splitlines()]
    case.log = (case.run_dir / "log.txt").read_text().splitlines()
    case.said = [line for line in case.log if "waiting for GitHub's API allowance" in line]


class SpentAllowance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the launch's read and the round's pass; the read before the post is refused, as on
        # 26 Oct
        reviewed(cls, lambda slug, reset, pr: [
            ("api rate_limit", {"out": allowance(0, 4000, reset)}),
            (f"api repos/{slug}/pulls/1", {"out": pr, "times": 2}),
            (f"api repos/{slug}/pulls/1", {"err": SPENT, "code": 1, "times": 1})])

    def test_the_run_waits_for_the_reset_then_posts_its_verdict_as_without_the_limit(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "review_posted", "head_sha")}, {
            "state": "pass", "verdict": "PASS", "review_posted": True, "head_sha": self.head})
        reviews = self.gh.pr(1)["reviews"]
        self.assertEqual([(review["state"], review["commit"]["oid"]) for review in reviews],
                         [("COMMENTED", self.head)])
        self.assertEqual(len(self.waits), 1, self.waits)
        self.assertAlmostEqual(self.waits[0][0], self.reset, delta=5)

    def test_its_record_carried_the_wait_so_the_stall_clock_starts_at_its_end(self):
        [record] = self.waits[0][1]
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["transient_wait"]["pid"], record["pid"])
        self.assertAlmostEqual(record["transient_wait"]["until"], self.reset, delta=5)

    def test_its_log_names_the_wait_once(self):
        until = datetime.fromtimestamp(self.reset, timezone.utc)
        self.assertEqual(len(self.said), 1, self.log)
        self.assertTrue(self.said[0].endswith(
            f"] waiting for GitHub's API allowance until {until:%H:%M} UTC"), self.said)


class AllowanceLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, lambda slug, reset, _pr: [
            ("api rate_limit", {"out": allowance(4999, 4999, reset)}),
            (f"api repos/{slug}/pulls/1/reviews", {"err": SPENT, "code": 1})])

    def test_a_failure_with_calls_left_ends_the_run_as_before_with_no_wait(self):
        self.assertEqual(self.done.code, 2, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "review_posted")}, {
            "state": "error", "verdict": "PASS", "review_posted": False})
        self.assertIn("API rate limit exceeded", self.state["error"])
        self.assertIn(["api", "rate_limit"], self.home.calls("gh"))
        self.assertEqual((self.waits, self.said), ([], []))


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Tick(unittest.TestCase):
    def test_a_tick_meeting_a_spent_allowance_goes_on_without_waiting(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        gh = GitHub(home)
        reset = int(time.time()) + 3600     # a tick waiting for it would outlast its bound
        gh.reply("api rate_limit", allowance(0, 0, reset))
        gh.reply("", err=SPENT, code=1)
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(home.calls("gh"), "the tick never asked GitHub")


if __name__ == "__main__":
    unittest.main()

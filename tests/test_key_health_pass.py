"""After a merge the project's `health:` command says when the change is live.

Done means live: a merged change counts as done once its project's `health:` line passes with
the change deployed.  Each `ak watch` tick runs it in the project's checkout with the merge
commit in AK_MERGE_SHA.  A pass marks the run live and types nothing into its seat; a failure
is recorded with its output and tried again on later ticks; one still failing three hours after
the merge is no longer run and waits to be handed back to the seat to fix the target.  None of
it pages the owner.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, the GitHub of fakegh.py, a seat from
akseat.py and the webhook of sink.py.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

# the live product's probe: it writes down the commit it was given and where it ran, and
# passes once live-ok exists
HEALTH = ('printf "%s\\n%s\\n" "$AK_MERGE_SHA" "$PWD" >"$HOME/probe"; '
          'test -e "$HOME/live-ok" || { echo down; exit 1; }')
PR = "https://github.com/acme/app/pull/7"
RUN = "20261020-1200-fix-api"


class Merged(unittest.TestCase):
    """A Home with project app merged by run RUN `age` seconds ago from seat acme, its checks
    green; `record` adds to or replaces the run's record, and None leaves a field out."""
    age, live, alive, record = 600, True, True, {}

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        cls.rig = Rig(cls.home, "app", files={"AGENTS.md": f"---\nhealth: {HEALTH}\n---\n"})
        cls.gh = GitHub(cls.home)
        cls.sha = cls.rig.head()
        cls.seat = Seat(cls.home, "acme", cwd=cls.rig.path, alive=cls.alive)
        if cls.live:
            cls.home.write("live-ok", "")
        cls.stage()
        cls.gh.check(cls.sha, "ci")
        now = time.time()
        record = {"run_id": RUN, "state": "pass", "verdict": "PASS", "merged": True,
                  "finished_at": now - cls.age, "started_at": now - cls.age - 600,
                  "repo": str(cls.rig.path), "pr": PR, "merge_sha": cls.sha,
                  "health": {"command": HEALTH}, "launched_session": "acme", **cls.record}
        cls.home.write(f".agentkit/runs/{RUN}/run.json",
                       {key: value for key, value in record.items() if value is not None})
        cls.tick()

    @classmethod
    def stage(cls):
        """What the test adds before the run's record is written."""

    @classmethod
    def tick(cls):
        (cls.home.path / "probe").unlink(missing_ok=True)
        done = cls.home.ak("watch")
        assert done.code == 0, done.out + done.err
        return done

    @classmethod
    def probed(cls):
        """What the last tick's probe was given, the merge commit then where it ran; else
        None."""
        probe = cls.home.path / "probe"
        return probe.read_text().splitlines() if probe.exists() else None

    @classmethod
    def run_record(cls):
        return json.loads((cls.home.path / f".agentkit/runs/{RUN}/run.json").read_text())

    def nobody_is_told(self):
        self.assertEqual(self.seat.typed(), "")
        self.assertEqual([r for r in self.sink.requests if r.method == "POST"], [])


class Live(Merged):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.first, cls.passed = cls.probed(), cls.run_record()
        cls.tick()

    def test_the_probe_runs_in_the_checkout_with_the_merge_commit(self):
        self.assertEqual(self.first, [self.sha, str(self.rig.path)])

    def test_a_passing_probe_marks_the_run_live_and_is_not_run_again(self):
        self.assertIsInstance(self.passed.get("live_at"), (int, float))
        self.assertIsInstance(self.passed.get("live_notified"), (int, float))
        self.assertNotIn("health", self.passed)
        self.assertIsNone(self.probed())

    def test_going_live_types_nothing_into_the_seat_and_pages_no_one(self):
        self.nobody_is_told()


class FoundFromTheMerge(Merged):
    """A merge recorded without its commit or its probe: GitHub names the commit, and the
    AGENTS.md it holds the probe."""
    record = {"pr": "https://github.com/acme/app/pull/1", "merge_sha": None, "health": None}

    @classmethod
    def stage(cls):
        cls.rig.branch("fix-api", {"api.py": "x = 2\n"})
        cls.gh.open_pr(cls.rig, "fix-api", title="Fix api")
        merged = cls.home.run("gh", "pr", "merge", "1", "--squash", cwd=cls.rig.path)
        assert merged.code == 0, merged.err
        cls.rig.git("pull", "-q")
        cls.sha = cls.gh.pr(1)["merge"]["commit"]

    def test_the_merge_commit_github_names_is_probed_and_the_run_goes_live(self):
        self.assertEqual(self.probed(), [self.sha, str(self.rig.path)])
        record = self.run_record()
        self.assertEqual(record.get("merge_sha"), self.sha)
        self.assertIsInstance(record.get("live_at"), (int, float))
        self.nobody_is_told()


class Failing(Merged):
    live = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.failed, cls.first = cls.run_record(), cls.probed()
        cls.home.write("live-ok", "")
        cls.tick()

    def test_a_failing_probe_is_recorded_with_its_output_and_the_run_is_not_live(self):
        self.assertEqual(self.first, [self.sha, str(self.rig.path)])
        self.assertEqual(self.failed.get("health"), {"command": HEALTH, "output": "down"})
        self.assertNotIn("live_at", self.failed)

    def test_the_next_tick_probes_again_and_its_pass_marks_the_run_live(self):
        self.assertEqual(self.probed(), [self.sha, str(self.rig.path)])
        record = self.run_record()
        self.assertIsInstance(record.get("live_at"), (int, float))
        self.assertNotIn("health", record)

    def test_neither_the_failure_nor_the_pass_after_it_tells_anyone(self):
        self.nobody_is_told()


class Expired(Merged):
    """Merged four hours ago, its probe failing since; its seat is closed."""
    age, live, alive = 4 * 3600, False, False
    record = {"health": {"command": HEALTH, "output": "down"}}

    def test_past_three_hours_the_probe_is_no_longer_run(self):
        self.assertIsNone(self.probed())
        record = self.run_record()
        self.assertNotIn("health", record)
        self.assertNotIn("live_at", record)

    def test_the_break_waits_to_be_handed_back_to_its_seat_and_pages_no_one(self):
        watch = json.loads((self.home.path / ".agentkit/state/watch.json").read_text())
        pending = watch["after_merge"]["github.com/acme/app"]["pending"]
        line = pending["line"]
        self.assertTrue(line.startswith(f"health: {HEALTH} failed on main after this merge: "
                                        f"{PR}"), line)
        self.assertTrue(line.endswith("Fix the target."), line)
        self.assertEqual({key: pending.get(key) for key in (
            "source", "check", "target", "session", "run", "typed", "sha")}, {
            "source": "health", "check": f"health: {HEALTH}", "target": "main",
            "session": "acme", "run": RUN, "typed": None, "sha": self.sha})
        self.nobody_is_told()


if __name__ == "__main__":
    unittest.main()

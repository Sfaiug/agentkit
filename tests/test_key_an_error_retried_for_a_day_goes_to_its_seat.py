"""An error retried for a day stops retrying, drops its stamp, and tells its seat once.

The tick retries an errored run on the transient ladder and then hourly, counting the day it
may retry from the error that started the ladder rather than from the latest failed retry or
when the run was launched.  Once that first error is a day old, the next tick starts no retry,
removes the retry stamps, and hands the error to its seat once; a run a retry carries on that
errors again later starts a new day and ladder of its own.
"""

import json
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
LOCKED = {"sh": "echo hello > retry.txt && git add -A && git commit -qm 'add retry.txt' && "
                'touch "$(git rev-parse --git-path index.lock)"',
          "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "wrong word", "expected fixed", "--run", "grep -qx fixed retry.txt"],
    ["done"]]}
LOCKED_AGAIN = {"sh": "echo fixed > retry.txt && git add -A && git commit -qm 'fix retry.txt' && "
                      'touch "$(git rev-parse --git-path index.lock)"',
                "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}
STAMPS = ("error_retry_at", "error_retries")


def offline(home):
    """Point HTTP proxies at a closed loopback port and restrict git to local files."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"), GIT_ALLOW_PROTOCOL="file")


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def backdate(run_dir, seconds):
    """Move every timestamp on the run's record back by `seconds`, as wall time passing does."""
    state = record(run_dir)
    for key, value in list(state.items()):
        if (key.endswith(("_at", "_since")) and isinstance(value, (int, float))
                and not isinstance(value, bool)):
            state[key] = value - seconds
    (run_dir / "run.json").write_text(json.dumps(state))
    return state


def unlock_index(home, worktree):
    lock = home.run("git", "-C", worktree, "rev-parse", "--path-format=absolute",
                    "--git-path", "index.lock").out.strip()
    Path(lock).unlink()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ErrorRetriedForADay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus"])
        cls.seat = Seat(home, "acme", planned=True)
        fakeadapter.install(home, claude=[LOCKED])
        cls.ended = home.ak("run", str(taskfile.write(home, rig.path, "Fix api")), "--no-merge",
                            env={"AGENTKIT_SESSION": "acme"})
        (home.path / ".agentkit/state/plan-acme.md").unlink()
        cls.run_dir = run_dir = taskfile.only_run(home)
        cls.born = record(run_dir)

        # Twenty-three hours after the first error: still under a day old, so the tick retries,
        # and the failed retry stamps a fresh finished_at while keeping the seat silent.
        cls.before_under_day = backdate(run_dir, 23 * 3600)
        cls.ticks = [home.tick()]
        cls.under_day = record(run_dir)
        cls.lines_under_day = cls.seat.lines()

        # Just over an hour more: the latest failed retry is only an hour old, but the error
        # that started the ladder is now past a day.
        cls.aged = backdate(run_dir, 3700)
        cls.ticks.append(home.tick())
        cls.day_old = record(run_dir)
        deadline = time.monotonic() + 5
        while not cls.seat.lines() and time.monotonic() < deadline:
            time.sleep(0.05)
        cls.first_lines = cls.seat.lines()

        # A further tick neither retries nor tells the seat a second time.
        cls.ticks.append(home.tick())
        cls.after = record(run_dir)
        cls.second_lines = cls.seat.lines()

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_under_a_day_from_the_first_error_the_run_is_still_retried(self):
        self.assertNotEqual(self.ended.code, 0, self.ended.out)
        self.assertEqual(self.under_day["state"], "error")
        self.assertGreater(self.under_day["finished_at"], self.before_under_day["finished_at"])
        self.assertEqual(self.under_day["error_retries"], 1)
        self.assertIn("error_retry_at", self.under_day)
        self.assertEqual(self.lines_under_day, [])

    def test_once_the_first_error_is_a_day_old_no_retry_starts_and_stamps_are_gone(self):
        self.assertEqual(self.day_old["state"], "error")
        self.assertEqual(self.day_old["finished_at"], self.aged["finished_at"])
        for key in STAMPS:
            self.assertNotIn(key, self.day_old)
        for key in STAMPS:
            self.assertNotIn(key, self.after)
        self.assertEqual(self.after["finished_at"], self.aged["finished_at"])

    def test_the_seat_is_given_the_runs_error_notice_once(self):
        self.assertEqual(len(self.first_lines), 1, self.first_lines)
        self.assertIn(self.run_dir.name, self.first_lines[0])
        self.assertIn("ERROR", self.first_lines[0])
        self.assertIn("index.lock", self.first_lines[0])
        self.assertEqual(self.second_lines, self.first_lines)
        self.assertTrue(self.day_old.get("handed_back"))
        self.assertIsNone(self.day_old.get("handback_note"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class FirstErrorAgeNotLaunchAge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus"])
        cls.seat = Seat(home, "acme", planned=True)
        cls.fake = fakeadapter.install(home, claude=[LOCKED, FINDING, LOCKED_AGAIN, "pass"])["claude"]
        task = taskfile.write(home, rig.path, "Fix retry", front={"rounds": 2})
        cls.ended = home.ak("run", str(task), "--no-merge", env={"AGENTKIT_SESSION": "acme"})
        (home.path / ".agentkit/state/plan-acme.md").unlink()
        cls.run_dir = run_dir = taskfile.only_run(home)

        # First error an hour ago on a run launched two days ago: still retried.
        backdate(run_dir, 3600)
        state = record(run_dir)
        two_days_ago = time.time() - 2 * 86400
        for key in ("started_at", "queued_at", "slot_started_at"):
            if key in state:
                state[key] = two_days_ago
        (run_dir / "run.json").write_text(json.dumps(state))
        unlock_index(home, state["worktree"])

        # The retry carries the run through round 1's review (FAIL) into round 2, where it
        # errors again: that later error starts a new ladder and a new day.
        cls.ticks = [home.tick()]
        cls.carried = record(run_dir)
        cls.carried_lines = cls.seat.lines()

        # Twenty-three and a half hours into the new ladder -- over a day past the first
        # error, still under a day past the second -- the tick still retries it.
        backdate(run_dir, 23 * 3600 + 1800)
        unlock_index(home, cls.carried["worktree"])
        cls.ticks.append(home.tick())
        cls.landed = record(run_dir)

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_run_launched_two_days_ago_whose_first_error_was_an_hour_ago_is_retried(self):
        self.assertNotEqual(self.ended.code, 0, self.ended.out)
        self.assertEqual(len(self.carried["round_summaries"]), 1)

    def test_a_retry_that_carries_on_and_errors_later_starts_a_new_day_and_ladder(self):
        self.assertEqual(self.carried["state"], "error")
        self.assertEqual(self.carried["error_retries"], 0)
        self.assertAlmostEqual(self.carried["error_retry_at"] - self.carried["finished_at"], 60,
                               delta=2)
        self.assertEqual((self.landed["state"], self.landed["verdict"]), ("pass", "PASS"))
        for key in STAMPS:
            self.assertIsNone(self.landed.get(key), key)
        self.assertEqual(self.carried_lines, [])


if __name__ == "__main__":
    unittest.main()

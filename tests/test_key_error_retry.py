"""A run that ended in error is retried by the tick on a ladder, at most hourly, until it works.

A git or provider failure under a run is the world, not the work: the run ends `error` with its
next retry stamped on its record, a minute after it ended, and each tick that finds the stamp
due resumes it and climbs a rung (1, 5, 15, 30 and 60 minutes, then hourly), so a run that
errors again waits longer and never restarts the ladder.  Without it a transient failure strands
the run.  Only an ending the tick may take up is retried: one whose worktree is gone, one handed
back, a day old or from a seat that is no more loses its stamp and waits for a person.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with
scripted harnesses from fakeadapter.py, each tick in the box `home.tick()` builds; the first
case's error is a real one, git's own lock left behind in the run's checkout.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import socket
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
# The executor's work, then the lock a crashed git leaves: every git write after it fails.
LOCKED = {"sh": "echo hello > retry.txt && git add -A && git commit -qm 'add retry.txt' && "
                'touch "$(git rev-parse --git-path index.lock)"',
          "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
STAMPS = ("error_retry_at", "error_retries")


def offline(home):
    """The tick asks the public boards over HTTP and fetches the checkout it runs from: every
    proxy names a loopback port nobody listens on, and git speaks only to files."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"), GIT_ALLOW_PROTOCOL="file")


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def until(run_dir, test, what, bound=60):
    """The run's record once `test` holds for it: a resumed run goes on in the background, and
    a record read as it is replaced is read again."""
    deadline = time.monotonic() + bound
    while True:
        try:
            if test(state := record(run_dir)):
                return state
        except (OSError, ValueError):
            state = {}
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}: {state.get('state')}")
        time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ErrorRetried(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus"])
        # the tick takes up only an ending whose seat is still there
        Seat(home, "acme", planned=True)
        holding, released = home.root / "adapters" / "held", home.root / "adapters" / "release"
        held = {"sh": f"touch '{holding}'; while [ ! -f '{released}' ]; do sleep 0.1; done",
                "final": "Handed in.", "hand_in": [["done"]]}
        cls.fake = fakeadapter.install(home, claude=[LOCKED, held])["claude"]
        cls.ended = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                            env={"AGENTKIT_SESSION": "acme"})
        cls.run_dir = run_dir = taskfile.only_run(home)
        cls.born = record(run_dir)
        cls.due(retries=0)
        # the lock is still there, so the resumed run errors again before its box goes
        cls.ticks = [home.tick()]
        cls.again = record(run_dir)
        lock = home.run("git", "-C", cls.born["worktree"], "rev-parse", "--path-format=absolute",
                        "--git-path", "index.lock").out.strip()
        Path(lock).unlink()
        # six retries spent already: no rung of the ladder is left below an hour
        cls.due(retries=6)
        # the box outlives the tick until the run it resumed ends, so the hold is seen beside it
        cls.before = time.time()
        with ThreadPoolExecutor(1) as pool:
            tick = pool.submit(home.tick)
            cls.held = until(run_dir, lambda _: holding.exists(), "resumed it again")
            cls.after = time.time()
            released.touch()
            cls.ticks.append(tick.result())
        cls.landed = record(run_dir)

    @classmethod
    def due(cls, retries):
        state = record(cls.run_dir)
        state.update(error_retries=retries, error_retry_at=time.time() - 1)
        (cls.run_dir / "run.json").write_text(json.dumps(state))

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_run_whose_git_fails_ends_in_error_with_its_first_retry_a_minute_on(self):
        self.assertNotEqual(self.ended.code, 0, self.ended.out)
        self.assertEqual(self.born["state"], "error")
        self.assertIn("index.lock", self.born["error"])
        self.assertEqual(self.born["error_retries"], 0)
        self.assertAlmostEqual(self.born["error_retry_at"] - self.born["finished_at"], 60,
                               delta=1)

    def test_a_due_retry_resumes_the_run_and_its_next_error_waits_on_the_next_rung(self):
        self.assertEqual(self.again["state"], "error")
        self.assertGreater(self.again["finished_at"], self.born["finished_at"])
        self.assertEqual(self.again["error_retries"], 1)
        self.assertAlmostEqual(self.again["error_retry_at"] - self.again["finished_at"], 300,
                               delta=1)

    def test_past_the_ladder_the_retry_after_is_an_hour_away(self):
        self.assertEqual(self.held["state"], "running")
        self.assertEqual(self.held["error_retries"], 7)
        self.assertGreaterEqual(self.held["error_retry_at"], self.before + 3600)
        self.assertLessEqual(self.held["error_retry_at"], self.after + 3600)

    def test_the_retried_run_carries_on_where_it_stopped_and_its_stamps_go(self):
        self.assertEqual((self.landed["state"], self.landed["verdict"]), ("pass", "PASS"))
        for key in STAMPS:
            self.assertIsNone(self.landed.get(key), key)
        self.assertEqual([run["role"] for run in self.fake.runs()], ["executor", "reviewer"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ErrorLeft(unittest.TestCase):
    """One tick over errored runs no retry is due for, or that the tick may not take up."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        akconfig.write(home, ["opus"])
        Seat(home, "acme")
        now = time.time()
        cls.later = now + 1200
        cls.runs = {
            "fix-api": cls.errored("fix-api", error_retries=2, error_retry_at=cls.later),
            "beta": cls.errored("beta", error_retries=None, error_retry_at=None),
            "gamma": cls.errored("gamma", worktree=str(home.path / ".agentkit/wt/gone")),
            "delta": cls.errored("delta", handed_back=now - 60),
            "eta": cls.errored("eta", started_at=now - 3 * 86400, finished_at=now - 2 * 86400),
            "zeta": cls.errored("zeta", launched_session="omega")}
        cls.before = time.time()
        cls.tick = home.tick()
        cls.after = time.time()

    @classmethod
    def errored(cls, name, **fields):
        """A run that ended in error two minutes ago from seat acme, its retry due, but for
        `fields`; a None one is left out, as a record from before errors had a retry."""
        home, now = cls.home, time.time()
        run_id = f"20261020-0900-{name}"
        worktree = home.path / ".agentkit/wt" / run_id
        worktree.mkdir(parents=True)
        repo = home.path / "code/widgets"
        state = {"run_id": run_id, "title": name, "state": "error", "verdict": "ERROR",
                 "error": "git fetch origin timed out after 120s", "started_at": now - 900,
                 "finished_at": now - 120, "launched_session": "acme", "repo": str(repo),
                 "worktree": str(worktree), "branch": f"ak/{name}", "base": "origin/main",
                 "base_sha": "a" * 40, "rounds": 3, "step": "executor", "error_retries": 1,
                 "error_retry_at": now - 30, **fields}
        state = {key: value for key, value in state.items() if value is not None}
        run_dir = home.write(f".agentkit/runs/{run_id}/run.json", state).parent
        (run_dir / "task.md").write_text(taskfile.write(home, repo, name=name).read_text())
        return run_dir

    def state(self, name):
        return record(self.runs[name])

    def setUp(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)

    def test_a_retry_not_yet_due_is_left_as_it_stands(self):
        state = self.state("fix-api")
        self.assertEqual(state["state"], "error")
        self.assertEqual((state["error_retries"], state["error_retry_at"]), (2, self.later))

    def test_an_error_with_no_retry_on_record_starts_the_ladder_at_its_foot(self):
        state = self.state("beta")
        self.assertEqual((state["state"], state["error_retries"]), ("error", 0))
        self.assertGreaterEqual(state["error_retry_at"], self.before + 60)
        self.assertLessEqual(state["error_retry_at"], self.after + 60)

    def test_an_error_the_tick_may_not_take_up_loses_its_retry_and_is_not_resumed(self):
        for name in ("gamma", "delta", "eta", "zeta"):
            with self.subTest(name):
                state = self.state(name)
                self.assertEqual(state["state"], "error")
                for key in STAMPS:
                    self.assertNotIn(key, state)


if __name__ == "__main__":
    unittest.main()

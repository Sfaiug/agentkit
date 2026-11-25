"""A resumed run whose checkout git does not know ends `exhausted`, not `error`, and is never
retried again.

When a worktree's `.git` names a directory that is not there -- as on a machine that took over as
home without the clone it was cut from -- git refuses `repository_lock` before any round runs.
Treating that refusal as `exhausted` stops the tick's error-retry ladder from re-running it for a
day before handing the ending to its seat; a run in a checkout git answers in carries on as usual.
Black-box over `AK_BIN` through tests/fixtures/akbin.py, on the same fixtures as
tests/test_key_error_retry.py.
"""

import json
from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
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


def stage_errored_run(case):
    """A run in `error` with a due retry stamp on a Home of its own."""
    home = Home()
    case.addClassCleanup(home.close)
    offline(home)
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus"])
    Seat(home, "acme", planned=True)
    fake = fakeadapter.install(home, claude=[LOCKED, "pass"])["claude"]
    ended = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                    env={"AGENTKIT_SESSION": "acme"})
    assert ended.code != 0, ended.out + ended.err
    run_dir = taskfile.only_run(home)
    state = record(run_dir)
    assert state["state"] == "error", state
    state.update(error_retries=0, error_retry_at=time.time() - 1)
    (run_dir / "run.json").write_text(json.dumps(state))
    return home, run_dir, state, fake


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class CheckoutGitDoesNotKnow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.run_dir, cls.born, cls.fake = stage_errored_run(cls)
        missing = cls.home.path / "missing-clone" / ".git" / "worktrees" / "gone"
        (Path(cls.born["worktree"]) / ".git").write_text(f"gitdir: {missing}\n")
        cls.first = cls.home.tick()
        cls.after_first = record(cls.run_dir)
        cls.status = cls.home.ak("run", "status", cls.run_dir.name)
        cls.second = cls.home.tick()
        cls.after_second = record(cls.run_dir)

    def test_every_tick_exits_zero(self):
        for done in (self.first, self.second):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_first_tick_resumes_and_ends_exhausted_without_retry_or_wait(self):
        self.assertIn(f"resumed {self.run_dir.name}: error retry 1",
                      self.first.out.splitlines())
        self.assertEqual(self.after_first["state"], "exhausted")
        self.assertIn(self.born["worktree"], self.after_first["error"])
        self.assertIn("not a git repository", self.after_first["error"])
        for key in STAMPS:
            self.assertNotIn(key, self.after_first)
        self.assertFalse(self.after_first.get("quota_dry"))
        self.assertNotIn("API/transport errors", self.after_first["error"])
        self.assertEqual(self.status.code, 0, self.status.out + self.status.err)
        rows = [line for line in self.status.out.splitlines() if self.born["title"] in line]
        self.assertEqual(len(rows), 1, self.status.out)
        self.assertIn("needs you", rows[0])
        self.assertNotIn("● working", rows[0])
        self.assertTrue(Path(self.born["worktree"]).is_dir())
        self.assertTrue((self.run_dir / "run.json").is_file())

    def test_second_tick_launches_no_resume(self):
        self.assertNotIn(f"resumed {self.run_dir.name}", self.second.out)
        self.assertEqual(self.after_second["state"], "exhausted")
        self.assertEqual(self.after_second["finished_at"], self.after_first["finished_at"])
        self.assertEqual(len(self.fake.runs()), 1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class CheckoutGitKnows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.run_dir, cls.born, cls.fake = stage_errored_run(cls)
        lock = cls.home.run("git", "-C", cls.born["worktree"], "rev-parse",
                            "--path-format=absolute", "--git-path", "index.lock").out.strip()
        Path(lock).unlink()
        cls.tick = cls.home.tick()
        cls.after = record(cls.run_dir)

    def test_tick_resumes_and_run_carries_on(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)
        self.assertIn(f"resumed {self.run_dir.name}: error retry 1",
                      self.tick.out.splitlines())
        self.assertEqual((self.after["state"], self.after["verdict"]), ("pass", "PASS"))
        for key in STAMPS:
            self.assertIsNone(self.after.get(key), key)
        self.assertEqual([run["role"] for run in self.fake.runs()], ["executor", "reviewer"])


if __name__ == "__main__":
    unittest.main()

"""A run spawns nothing that inherits the launcher's keyboard or the seat's state.

Done-when commands run with stdin on /dev/null (a foreground `ak run` must never
hand its tty to a command that asks for input), and config.child_env() drops
IDLE_COMPACT_STATE (a seat's worker must never overwrite the seat's own
idle-compact state file).  stdlib only, no harness calls, no tmux.
"""

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run, watch

# What a suite running inside a seat hands to the `ak run` it starts: the seat lookup
# then sees the suite's own servers, where the live launcher seat is nowhere to be found.
REDIRECT = {orch.SOCKET_ENV: "agentkit-test", "TMUX_TMPDIR": "/tmp/smoke-test-tmux"}


@contextmanager
def stdin_from(path):
    """Point this process's fd 0 at `path`, restoring it afterwards.

    run_done_when takes no stdin of its own, so without this the test would only
    prove what the test runner happened to be started with.  A sentinel file
    makes the inheritance check hermetic: old code shows the sentinel, fixed
    code shows /dev/null.
    """
    saved = os.dup(0)
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.dup2(fd, 0)
        yield
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(fd)


class RunIsolation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="run-isolation-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.sentinel = self.root / "sentinel.txt"
        self.sentinel.write_text("this keyboard must not leak\n")
        self.log_path = self.root / "donewhen.log"
        self.artifacts = set()

    def done_when(self, *cmds):
        return run.run_done_when(list(cmds), self.root, self.log_path, self.artifacts)

    def test_done_when_stdin_is_dev_null(self):
        with stdin_from(self.sentinel):
            ok, text = self.done_when("readlink /proc/self/fd/0")
        self.assertTrue(ok, text)
        self.assertIn("/dev/null", text)

    def test_done_when_stdin_reading_gets_eof(self):
        with stdin_from(self.sentinel):
            ok, text = self.done_when('read -r x; echo "rc=$?"')
        self.assertTrue(ok, text)
        self.assertIn("rc=1", text)

    def test_done_when_does_not_carry_idle_compact_state(self):
        with patch.dict(os.environ, {"IDLE_COMPACT_STATE": "/tmp/x.json"}):
            ok, text = self.done_when('echo "state=${IDLE_COMPACT_STATE-unset}"')
        self.assertTrue(ok, text)
        self.assertIn("state=unset", text)

    def test_child_env_drops_idle_compact_state(self):
        with patch.dict(os.environ, {"IDLE_COMPACT_STATE": "/tmp/x.json", "KEEP_ME": "1",
                                     config.RUN_DIR_ENV: "/tmp/run", "AK_RUN_SCOPE": "old.scope"}):
            env = config.child_env()
        self.assertNotIn("IDLE_COMPACT_STATE", env)
        self.assertNotIn(config.RUN_DIR_ENV, env)
        self.assertNotIn("AK_RUN_SCOPE", env)
        self.assertEqual(env.get("KEEP_ME"), "1")


class OrphanAnnounce(unittest.TestCase):
    """The orphan report asks after the launcher in both worlds that may hold it.

    A run started by a suite inside a live seat inherits the suite's redirected seat
    lookup; asking only there mistakes the live launcher for a gone one and a run
    nobody orphaned speaks (check 4d).  But $TMUX_TMPDIR is also legitimately set, so
    the inherited lookup always goes first.  The seat lookup itself is faked: no tmux.

    v5ay: a launcher that is there is handed the ending instead of being left alone, so
    these pin the lookup and that the owner still hears nothing; the hand-back itself is
    faked, because this class deliberately does not isolate the real state directory.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="orphan-")
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)
        self.state = {"launched_session": "herdr", "state": "pass",
                      "title": "Smoke make hello pass"}

    def test_watched_launcher_stays_quiet_despite_redirect(self):
        calls = []

        def fake_watching(name):
            calls.append({key: os.environ.get(key) for key in REDIRECT})
            self.assertEqual(name, "herdr")
            # the launcher lives on the toolkit's own servers, not the suite's
            return orch.SOCKET_ENV not in os.environ

        lines = []
        before = {key: os.environ.get(key) for key in REDIRECT}
        with patch.dict(os.environ, REDIRECT), \
                patch.object(orch, "watching", fake_watching), \
                patch.object(run, "hand_back") as handed:
            run.announce(dict(self.state), self.run_dir, lines.append)
        self.assertEqual([c[orch.SOCKET_ENV] for c in calls],
                         ["agentkit-test", None])
        self.assertEqual(lines, [])            # the owner hears nothing about a live seat
        handed.assert_called_once()            # the seat that is there gets the ending
        self.assertFalse((self.run_dir / "run.json").exists())
        self.assertEqual({key: os.environ.get(key) for key in REDIRECT}, before)

    def test_launcher_on_redirected_servers_stays_quiet_first_look(self):
        calls = []

        def fake_watching(name):
            calls.append(os.environ.get("TMUX_TMPDIR"))
            return True

        lines = []
        with patch.dict(os.environ, {"TMUX_TMPDIR": "/legit/socket-dir"}), \
                patch.object(orch, "watching", fake_watching), \
                patch.object(run, "hand_back") as handed:
            run.announce(dict(self.state), self.run_dir, lines.append)
        # legitimately set: the lookup that matters keeps it, and one look is enough
        self.assertEqual(calls, ["/legit/socket-dir"])
        self.assertEqual(lines, [])
        handed.assert_called_once()

    def test_gone_launcher_still_reports(self):
        lines = []
        # v5s changed announce's orphan path: a gone launcher is reopened first and the needs
        # fires only when the seat cannot be reopened.  seat_closed=True pins that surviving
        # case -- no seat to reopen, so the needs still goes out with its text -- and, because
        # this class deliberately does not isolate config.STATE, also keeps announce from
        # reading the real state and reopening the real seat this name happens to match.
        with patch.dict(os.environ, REDIRECT), \
                patch.object(orch, "watching", return_value=False), \
                patch.object(watch, "seat_closed", return_value=True), \
                patch.object(notify, "shaped", return_value=1) as shaped:
            run.announce(dict(self.state), self.run_dir, lines.append)
        self.assertTrue(any("is gone" in line for line in lines), lines)
        shaped.assert_called_once()
        self.assertEqual(shaped.call_args.kwargs.get("session"), "herdr")


if __name__ == "__main__":
    unittest.main()

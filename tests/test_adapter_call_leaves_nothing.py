"""An adapter call past ak's limit is killed with what it runs (`config.run_adapter`).

Inside the adapters every `timeout` sends KILL a second after its TERM: `agy` catches TERM.
Offline: the adapter is a fake, every process it starts the test's own.
"""

from contextlib import nullcontext
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, host, usage  # noqa: E402

LIMIT = 2   # seconds: long enough for the fake to start them all, short enough to wait out

# Each process ak must kill writes its pid to $PIDS, each it must leave to $KEPT.  A slow call
# starts children that ignore TERM, as a CLI that catches it does: one beside it and one under
# timeout(1), which leads a group of its own and keeps in it one more that has left the call's
# tree; one that joins the caller's own group; and a service in a session of its own.
FAKE = """#!/usr/bin/env bash
echo $$ >>"$PIDS"
if [ -z "$SLOW" ]; then
  sleep 600 >/dev/null 2>&1 & echo $! >>"$KEPT"
  printf 'm1\\tModel one\\tlow high\\nm2\\t\\tnone\\n'; echo 'listing...' >&2; exit 0
fi
setsid sh -c 'echo $$ >>"$KEPT"; exec sleep 600' >/dev/null 2>&1 &
"$IGNORE" &
python3 -c 'import os; os.setpgid(0, int(os.environ["GROUP"])); os.execv(os.environ["IGNORE"], ["ignore"])' &
timeout 600 sh -c 'echo $PPID >>"$PIDS"; ("$IGNORE" &); exec "$IGNORE"'
"""
IGNORE = """#!/bin/sh
trap "" TERM; echo $$ >>"$PIDS"; exec sleep 600
"""


def running(pid):
    return (stat := host.proc_stat(pid)) is not None and not stat.exited


class AdapterCall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-adapter-call-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, script in (("acme.sh", FAKE), ("ignore", IGNORE)):
            (self.root / name).write_text(script)
            (self.root / name).chmod(0o755)
        self.pids, self.kept = self.root / "pids", self.root / "kept"
        env = patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(self.root),
                                      "HOME": str(self.root), "PIDS": str(self.pids),
                                      "KEPT": str(self.kept), "SLOW": "",
                                      "IGNORE": str(self.root / "ignore"),
                                      "GROUP": str(os.getpgrp())})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for path in (self.pids, self.kept):
            for pid in path.read_text().split() if path.exists() else ():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass

    def started(self, path):
        return [int(pid) for pid in path.read_text().split()]

    def assert_killed(self, give_up):
        # in the caller's own group, as the menu's terminal holds what the menu runs
        sibling = subprocess.Popen(["sleep", "600"])
        self.addCleanup(sibling.wait)
        self.addCleanup(sibling.kill)
        os.environ["SLOW"] = "1"
        for proc in (None, self.root / "no-proc"):
            self.kill_all()
            self.pids.write_text("")
            self.kept.write_text("")
            with self.subTest(proc=proc):
                with patch.object(host, "PROC", proc) if proc else nullcontext():
                    give_up()
                started = self.started(self.pids)
                self.assertEqual(len(started), 6, "the adapter, its two, timeout, its two")
                self.assertEqual([pid for pid in started if running(pid)], [])
                self.assertIsNone(sibling.poll(), "the caller's own group is never killed")
                [service] = self.started(self.kept)
                self.assertTrue(running(service), "a session of its own is never killed")

    def test_a_listing_past_its_limit_is_killed_with_what_it_runs(self):
        call = config.run_adapter
        with patch.object(config, "run_adapter",
                          lambda argv, timeout, **kw: call(argv, LIMIT, **kw)):
            self.assert_killed(lambda: self.assertEqual(config._listed("acme", None, []), []))

    def test_a_usage_call_past_its_limit_is_killed_with_what_it_runs(self):
        self.assert_killed(
            lambda: self.assertIsNone(usage._adapter_json("acme", "reset-status", LIMIT)))

    def test_a_listing_in_time_reads_as_before_and_kills_nothing(self):
        self.assertEqual(config._listed("acme", None, []), [
            {"id": "m1", "label": "Model one", "efforts": ["low", "high"]},
            {"id": "m2", "label": "m2", "efforts": ["none"]}])
        [left] = self.started(self.kept)
        self.assertTrue(running(left), "what a call in time leaves is the leftover sweep's")

    def test_every_timeout_in_an_adapter_sends_kill_after_its_term(self):
        bare = re.compile(r'(?<![-\w])timeout(?= +[0-9$]|")')
        for script in sorted((REPO / "adapters").glob("*.sh")):
            for number, line in enumerate(script.read_text().splitlines(), 1):
                with self.subTest(at=f"{script.name}:{number}"):
                    self.assertIsNone(bare.search(line), "timeout -k <seconds> ...")


if __name__ == "__main__":
    unittest.main()

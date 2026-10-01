"""Every harness's turn ends its detached commands before the foreground finish call."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker


ADAPTER = r'''import json, os, subprocess, sys, time
from pathlib import Path
if sys.argv[1] == "auth":
    print("fixture token")
    sys.exit(0)
out = Path(sys.argv[6])
root = Path(os.environ["TURN_FIXTURE"])
calls = root / "calls.jsonl"
n = len(calls.read_text().splitlines()) if calls.exists() else 0
with calls.open("a") as fh:
    fh.write(json.dumps({"marker": os.environ["AGENTKIT_RUN"],
                         "prompt": Path(sys.argv[5]).read_text(),
                         "session": sys.argv[7:]}) + "\n")
if n == 0 or os.environ.get("TURN_LEAK_EVERY") == "1":
    pid = int(subprocess.check_output(
        ["bash", "-c", "nohup sleep 300 </dev/null >/dev/null 2>&1 & echo $!"], text=True))
    (out / "leftover.pid").write_text(str(pid))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if Path(f"/proc/{pid}/cmdline").read_bytes() == b"sleep\x00300\x00":
            break
        time.sleep(.01)
    else:
        raise RuntimeError("fixture sleeper never started")
(out / "final.md").write_text("## Summary\nFinished." if n else "## Summary\nStarted.")
(out / "session_id").write_text("fixture-session")
(out / "stderr.log").write_text("")
(out / "events.jsonl").write_text("")
'''


class TurnLeftoverProcesses(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-turn-processes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "TURN_FIXTURE": str(self.root), "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", config.SESSION_ENV: "", config.RUN_DIR_ENV: ""}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        run_id = f"acme-turn-{self.root.name}"
        self.marker = worker.run_marker(run_id)
        self.stack.enter_context(patch.object(run._RUN_CONTEXT, "state",
                                              {"run_id": run_id, "run_depth": 0},
                                              create=True))
        self.stack.enter_context(patch.object(run, "memory_cap_note"))
        self.stack.enter_context(patch.object(run, "note_turn_meters"))
        self.stack.enter_context(patch.object(run.usage, "account", return_value=(None, True)))
        adapter = self.root / "adapter.sh"
        adapter.write_text(f"#!{sys.executable}\n{ADAPTER}")
        adapter.chmod(0o755)
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        self.cfg = {"models": {"w": {"harness": "codex", "model": "fixture", "effort": "low",
                                    "provider": "fixture"}}, "providers": {"fixture": {}}}
        self.logs = []
        self.children = []
        # Restrict every /proc scan to PIDs this fixture started, including the adapter's
        # detached child. The caller's real ancestry and the host's processes are not read.
        listdir = os.listdir

        def fixture_entries(path):
            if str(path) == "/proc":
                return [str(pid) for pid in self.pids()]
            return listdir(path)

        self.stack.enter_context(patch.object(worker.os, "listdir", side_effect=fixture_entries))
        self.stack.enter_context(patch.object(worker, "_lineage", return_value={os.getpid()}))
        kill = os.kill

        def fixture_kill(pid, sig):
            if sig:
                self.assertIn(pid, self.pids(), "signal outside fixture")
            return kill(pid, sig)

        self.stack.enter_context(patch.object(worker.os, "kill", side_effect=fixture_kill))
        self.addCleanup(self.reap)

    def pids(self):
        return [proc.pid for proc in self.children] + [
            int(path.read_text()) for path in self.root.rglob("leftover.pid")]

    def reap(self):
        for pid in self.pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for proc in self.children:
            proc.wait(timeout=5)

    def launch(self, role="executor"):
        out = self.root / "run" / "round-1" / role
        return run.call_retrying(self.cfg, "w", "task body", self.root, out,
                                 role, None, self.logs.append, limit=30)

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def spawn(self, marker):
        proc = subprocess.Popen(["sleep", "300"], env={**os.environ, worker.RUN_MARKER: marker},
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.children.append(proc)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if f"{worker.RUN_MARKER}={marker}".encode() in \
                    Path(f"/proc/{proc.pid}/environ").read_bytes().split(b"\0"):
                return proc
            time.sleep(.01)
        self.fail("fixture sleeper never started")

    def test_non_claude_nohup_gets_one_foreground_finish(self):
        code, text, session, dead = self.launch()
        self.assertEqual(worker.marked_pids(self.marker), [], "turn left its nohup child running")
        self.assertTrue(any("sleep 300" in line for line in self.logs), self.logs)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertIn(run.FINISH_IN_FOREGROUND, calls[1]["prompt"])
        self.assertEqual(calls[1]["session"], ["fixture-session"])
        self.assertEqual((code, text, session, dead),
                         (0, "## Summary\nFinished.", "fixture-session", False))
        self.assertTrue(all(call["marker"].startswith(f"{self.marker}/turn-") for call in calls))
        self.assertNotEqual(calls[0]["marker"], calls[1]["marker"])

    def test_turn_cleanup_spares_suite_helpers_and_other_turns(self):
        markers = (self.marker, f"{self.marker}/suite", f"{self.marker}/turn-other")
        neighbours = [self.spawn(marker) for marker in markers]
        self.launch()
        for proc in neighbours:
            self.assertIsNone(proc.poll(), "turn cleanup killed a neighbour")
        self.assertEqual(set(worker.marked_pids(self.marker)), {proc.pid for proc in neighbours})

    def test_cleanup_works_on_every_other_harness(self):
        for harness in ("claude", "muse", "opencode", "grokbuild", "antigravity"):
            with self.subTest(harness=harness):
                self.cfg["models"]["w"]["harness"] = harness
                (self.root / "calls.jsonl").write_text("")
                self.launch()
                self.assertEqual(worker.marked_pids(self.marker), [])
                self.assertEqual(len(self.calls()), 2)

    def test_reviewer_leftovers_share_the_one_finish_and_verdict_ask(self):
        self.launch("reviewer")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertIn(run.FINISH_IN_FOREGROUND, calls[1]["prompt"])
        self.assertIn(run.NO_VERDICT_ASK, calls[1]["prompt"])
        self.assertEqual(worker.marked_pids(self.marker), [])

    def test_second_unfinished_turn_is_stopped_and_warned_without_a_third_call(self):
        with patch.dict(os.environ, {"TURN_LEAK_EVERY": "1"}):
            self.launch()
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(worker.marked_pids(self.marker), [])
        self.assertEqual(sum("sleep 300" in line for line in self.logs), 2)
        self.assertEqual(sum("background again" in line for line in self.logs), 1)

    def test_failed_auth_turn_still_ends_its_processes(self):
        helper = self.spawn(self.marker)

        def expired(*_args, env=None, **_kw):
            self.spawn(env[worker.RUN_MARKER])
            raise worker.LoginExpired("codex", "fixture token expired")

        with patch.object(worker, "call", side_effect=expired), \
                self.assertRaises(worker.LoginExpired):
            self.launch()
        self.assertEqual(worker.marked_pids(self.marker), [helper.pid])
        self.assertTrue(any("sleep 300" in line for line in self.logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)

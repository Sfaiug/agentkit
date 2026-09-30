"""A run's memory cap ends the process that grew, and only the third such kill ends the run.

The fakes are tests/test_memory_cap.py's: a fake /proc/self/cgroup puts this process in the
run's scope, a fake cgroup tree holds that scope's memory.events, and every scope stop and
marked kill is injected.  A done-when command stands in for the kernel: it writes the new
oom_kill count and exits 137, as the command that grew does.  No unit is started or stopped
and no pid is signalled.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, worker

RUN_ID = "20260930-1700-grower"
SCOPE = f"agentkit-run-{RUN_ID}"
CGROUP = f"/user.slice/user@1000.service/agentkit.slice/agentkit-runs.slice/{SCOPE}.scope"
HIT = "memory cap 4 GB hit ({} of 3): the process that grew was ended"


class EndsTheGrower(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-memory-grower-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        own = self.root / "own-cgroup"
        own.write_text(f"0::{CGROUP}\n")
        self.events = self.root / "cgroup" / CGROUP.lstrip("/") / "memory.events"
        self.events.parent.mkdir(parents=True)
        self.events.write_text("oom 0\noom_kill 0\n")
        self.stopped = []
        for target, name, fake in (
                (orch, "OWN_CGROUP", own), (orch, "CGROUP_ROOT", self.root / "cgroup"),
                (orch, "stop_scope", lambda scope, log=None, wait=True:
                 self.stopped.append(scope) or True),
                (worker, "kill_marked", lambda *_a, **_k: True),
                (run, "dirty_paths", lambda _wt: [])):
            self.stack.enter_context(patch.object(target, name, fake))
        self.stack.enter_context(patch.dict(run._OOM_SEEN, clear=True))
        self.run_dir = config.RUNS / RUN_ID
        self.run_dir.mkdir()
        (self.run_dir / "task.md").write_text("---\nrepo: none\n---\n# fix-api\n")
        run.save_state(self.run_dir, {
            "run_id": RUN_ID, "title": "fix-api", "state": "running", "verdict": None,
            "scope": SCOPE, "memory_cap_mb": 4096, "started_at": time.time(),
            "round_summaries": [], **run.process_owner()})
        self.never = self.root / "never"

    def kill(self, count):
        """A command the kernel ended at the cap: the scope counts it, and it exits 137."""
        return (f"printf 'oom {count}\\noom_kill {count}\\n' > {shlex.quote(str(self.events))}; "
                "exit 137")

    def gate(self, cmds, log):
        return run.run_done_when(cmds, self.root, self.run_dir / "donewhen.log", set(),
                                 log=log, run_dir=self.run_dir)

    def test_the_scope_asks_for_oom_policy_continue(self):
        with patch.object(orch, "scope_oom_policy", return_value=True), \
                patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "can_scope", return_value=True):
            _cap, props = run.run_scope_limits(ceiling_mb=10000)
            argv, _env = orch.in_slice(["sleep", "1"], SCOPE,
                                       target_slice=orch.run_slice_name(), properties=props)
        self.assertIn("OOMPolicy=continue", props)
        self.assertEqual(argv[argv.index("OOMPolicy=continue") - 1], "-p")
        # An older systemd refuses a scope that names it, and the run would start uncapped.
        with patch.object(orch, "scope_oom_policy", return_value=False):
            _cap, props = run.run_scope_limits(ceiling_mb=10000)
        self.assertFalse(any(str(item).startswith("OOMPolicy") for item in props))
        self.assertIn("MemoryMax=4000M", props)

    def test_the_version_is_the_managers_own_answer(self):
        # A library tag is the build's to choose, bare digits included (`1`, `999`): only
        # the manager's own answer is its version.
        def asked(said, manager=True):
            orch._OOM_POLICY.clear()
            calls = []

            def systemctl(argv, **_kw):
                calls.append(argv)
                if isinstance(said, BaseException):
                    raise said
                return subprocess.CompletedProcess(argv, 0, said, "")
            with patch.object(orch, "user_manager", return_value=manager), \
                    patch.object(orch.subprocess, "run", side_effect=systemctl):
                return orch.scope_oom_policy(), calls
        self.addCleanup(orch._OOM_POLICY.clear)
        for said, takes in (("257.13-1~deb13u1\n", True), ("253\n", True),
                            ("252.3-2\n", False), ("", False),
                            (OSError("no systemctl"), False),
                            (subprocess.TimeoutExpired("systemctl", 30), False)):
            answer, calls = asked(said)
            self.assertEqual(answer, takes, said)
            self.assertEqual(calls, [["systemctl", "--user", "show", "-p", "Version", "--value"]])
        # asked once per process
        orch._OOM_POLICY.clear()
        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, "257\n", "")) as run_mock:
            self.assertTrue(orch.scope_oom_policy())
            self.assertTrue(orch.scope_oom_policy())
        self.assertEqual(run_mock.call_count, 1)
        # no manager to ask: nothing is started, and the scope keeps the default
        self.assertEqual(asked("257\n", manager=False), (False, []))

    def test_the_first_two_kills_leave_the_run_going(self):
        logs = []
        ok, text = self.gate([self.kill(1), self.kill(2), "true"], logs.append)
        self.assertFalse(ok)                 # a command that was killed still failed
        self.assertEqual([line for line in logs if " hit " in line],
                         [HIT.format(1), HIT.format(2)])
        self.assertIn("$ true\n[exit 0]", text)
        state = run.read_state(self.run_dir)
        self.assertEqual(state["state"], "running")
        self.assertNotIn("error", state)
        self.assertEqual(self.stopped, [])

    def test_the_third_kill_ends_the_run_fail_with_the_reason(self):
        cmds = [self.kill(1), self.kill(2), self.kill(3), f"touch {shlex.quote(str(self.never))}"]
        with redirect_stdout(io.StringIO()):
            code = run.drive(config.load(), self.run_dir, {}, run.logger(self.run_dir, True),
                             job=lambda: self.gate(cmds, run.logger(self.run_dir, True)))
        self.assertEqual(code, 1)
        state = run.read_state(self.run_dir)
        self.assertEqual((state["state"], state["verdict"]), ("fail", "FAIL"))
        self.assertEqual(state["error"], "killed: memory cap 4 GB")
        log = (self.run_dir / "log.txt").read_text()
        for count in (1, 2, 3):
            self.assertIn(HIT.format(count), log)
        self.assertIn("killed: memory cap 4 GB", log)
        self.assertIn("killed: memory cap 4 GB", (self.run_dir / "result.md").read_text())
        self.assertFalse(self.never.exists())    # nothing ran after the third kill
        self.assertIn(SCOPE, self.stopped)       # the loop stopped its own scope last

    def test_a_worker_the_cap_killed_resumes_until_the_third(self):
        # The reviewer's case: the worker itself was the process that grew, twice. Two
        # SIGKILLs inside a minute would park the run as someone's on purpose; the cap's
        # kills resume instead, and its own count ends the run at the third.
        calls, logs = [], []

        def worker_call(cfg, name, text, workspace, target, role, session, **_kw):
            calls.append(session)
            Path(target).mkdir(parents=True, exist_ok=True)
            if len(calls) <= kills:
                self.events.write_text(f"oom {len(calls)}\noom_kill {len(calls)}\n")
                return -9, "", "session-1", False
            (Path(target) / "final.md").write_text("done\n")
            return 0, "done", "session-1", False
        out = self.run_dir / "round-1" / "executor"
        for kills in (2, 3):
            calls.clear()
            self.events.write_text("oom 0\noom_kill 0\n")
            run._OOM_SEEN.clear()
            with patch.object(worker, "call", side_effect=worker_call):
                if kills == 2:
                    code, _text, _sid, _killed = run.call_retrying(
                        config.load(), "opus", "fix-api", self.root, out, "executor", None,
                        logs.append)
                    self.assertEqual((code, len(calls)), (0, 3))
                    self.assertEqual([line for line in logs if " hit " in line],
                                     [HIT.format(1), HIT.format(2)])
                    self.assertEqual(sum("at the memory cap; resuming" in line
                                         for line in logs), 2)
                else:
                    with self.assertRaises(run.MemoryCapped):
                        run.call_retrying(config.load(), "opus", "fix-api", self.root, out,
                                          "executor", None, logs.append)
                    self.assertEqual(len(calls), 3)

    def test_a_seat_scope_is_not_the_runs(self):
        # A run from a seat's shell sits in the seat's scope, whose kills are not the run's.
        (self.root / "own-cgroup").write_text(
            "0::/user.slice/user@1000.service/agentkit.slice/agentkit-seats.slice/"
            "agentkit-seat-acme.scope\n")
        logs = []
        self.gate([self.kill(3)], logs.append)
        self.assertEqual([line for line in logs if " hit " in line], [])
        self.assertEqual(run.read_state(self.run_dir)["state"], "running")


if __name__ == "__main__":
    unittest.main()

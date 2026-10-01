"""A run's memory cap ends the process that grew, and the run goes on.

A run scope asks for OOMPolicy=continue when the user manager is systemd 253 or
later, so the kernel ends only the process past the cap; the loop logs each kill
its scope counts, and the run goes on as after any failed command.  Nothing here
asks the real manager or reads a real cgroup: `systemctl` is a fake
`subprocess.run`, and the loop's cgroup and its memory.events are files in a
temporary directory.
"""

from contextlib import ExitStack
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, worker

SCOPE = "agentkit-run-20260930-2300-acme"
CGROUP = ("user.slice/user-1000.slice/user@1000.service/agentkit-test.slice/"
          f"agentkit-test-runs.slice/{SCOPE}.scope")
HIT = "memory cap 4 GB hit: the process that grew was ended"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ak-grower-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        orch._OOM_POLICY.clear()
        self.addCleanup(orch._OOM_POLICY.clear)


class Policy(Sandbox):
    def limits(self, said, manager=True):
        """The run scope's properties, and every systemctl asked, over two launches."""
        asked = []

        def fake_run(argv, **_kw):
            asked.append(argv)
            if isinstance(said, Exception):
                raise said
            return subprocess.CompletedProcess(argv, 0, stdout=said, stderr="")

        orch._OOM_POLICY.clear()
        with patch.object(orch, "user_manager", return_value=manager), \
                patch.object(orch.subprocess, "run", side_effect=fake_run):
            _cap, props = run.run_scope_limits(ceiling_mb=10000)
            self.assertEqual(run.run_scope_limits(ceiling_mb=10000)[1], props)
        return props, asked

    def test_a_manager_of_253_or_later_is_asked_for_continue_once(self):
        for said in ("253\n", "257.13-1~deb13u1\n"):
            props, asked = self.limits(said)
            self.assertEqual(props[-2:], ("-p", "OOMPolicy=continue"), said)
            self.assertEqual(asked, [["systemctl", "--user", "show", "-p", "Version",
                                      "--value"]])

    def test_an_older_manager_or_no_answer_keeps_the_stop(self):
        for said in ("252.30-1\n", "", "debian\n", OSError("no systemctl"),
                     subprocess.TimeoutExpired("systemctl", 30)):
            props, asked = self.limits(said)
            self.assertNotIn("OOMPolicy=continue", props, said)
            self.assertIn("MemoryMax=4000M", props)
            self.assertEqual(len(asked), 1)

    def test_no_manager_is_never_asked(self):
        props, asked = self.limits("257\n", manager=False)
        self.assertNotIn("OOMPolicy=continue", props)
        self.assertEqual(asked, [])

    def test_launches_at_once_ask_once(self):
        # a job's delivery threads launch together; the second waits for the first's answer
        asked, both = [], threading.Barrier(2, timeout=1)

        def fake_run(argv, **_kw):
            asked.append(argv)
            try:
                both.wait()     # a second question, if one were asked, would arrive now
            except threading.BrokenBarrierError:
                pass
            return subprocess.CompletedProcess(argv, 0, stdout="257\n", stderr="")

        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch.subprocess, "run", side_effect=fake_run):
            launches = [threading.Thread(target=orch.scope_oom_policy) for _ in range(2)]
            for launch in launches:
                launch.start()
            for launch in launches:
                launch.join()
            self.assertTrue(orch.scope_oom_policy())
        self.assertEqual(len(asked), 1)


class Loop(Sandbox):
    def setUp(self):
        super().setUp()
        own = self.root / "own-cgroup"
        own.write_text(f"0::/{CGROUP}\n")
        self.events = self.root / "cgroup" / CGROUP / "memory.events"
        self.events.parent.mkdir(parents=True)
        self.kills(0)
        self.stack.enter_context(patch.object(orch, "OWN_CGROUP", own))
        self.stack.enter_context(patch.object(orch, "CGROUP_ROOT", self.root / "cgroup"))
        self.stack.enter_context(patch.object(worker, "kill_marked", return_value=True))
        os.environ.pop(run.OOM_LOGGED, None)    # the sandbox's patch.dict puts it back
        self.run_dir = config.RUNS / "20260930-2300-acme"
        self.run_dir.mkdir(parents=True)
        run.save_state(self.run_dir, {
            "run_id": self.run_dir.name, "state": "running", "verdict": None,
            "scope": SCOPE, "memory_cap_mb": 4096})
        self.lines = []

    def kills(self, count):
        self.events.write_text(f"low 0\nhigh 0\nmax 9\noom {count}\noom_kill {count}\n")

    def test_a_done_when_command_past_the_cap_fails_and_the_run_goes_on(self):
        # the command is the process that grew: it exits 137, and its re-run is
        # ended the same way without a new kill being counted twice
        cmd = f"printf 'oom_kill 1\\n' > {self.events}; exit 137"
        ok, text = run.run_done_when([cmd], self.root, self.root / "donewhen.log", set(),
                                     limit=60, silence=60, log=self.lines.append,
                                     run_dir=self.run_dir)
        self.assertFalse(ok)
        self.assertIn("[exit 137]", text)
        self.assertEqual(self.lines.count(HIT), 1)
        self.assertEqual(run.read_state(self.run_dir)["state"], "running")

    def test_each_kill_in_a_worker_turn_is_logged_once(self):
        cfg = {"models": {"w": {"harness": "claude", "model": "m", "effort": "e",
                                "provider": "p"}},
               "providers": {"p": {}}}
        counts = iter((2, 2, 3))

        def turn(*_args, **_kw):
            # a test the worker ran grew past the cap; the worker read its 137 and went on
            self.kills(next(counts))
            return 0, "## Summary\nall done", None, False

        out = self.run_dir / "round-1" / "executor"
        with patch.object(worker, "call", side_effect=turn):
            for _ in range(3):
                code, *_rest = run.call_retrying(cfg, "w", "do the thing", self.root, out,
                                                 "executor", None, self.lines.append)
                self.assertEqual(code, 0)
        self.assertEqual(self.lines.count(HIT), 3)
        self.assertEqual(run.read_state(self.run_dir)["state"], "running")

    def test_a_reviewer_and_a_suite_ending_at_once_log_a_kill_once(self):
        self.kills(1)
        both = threading.Barrier(2, timeout=1)

        def log(line):
            self.lines.append(line)
            try:
                both.wait()     # the other thread's line, if it said one, would arrive now
            except threading.BrokenBarrierError:
                pass

        ending = [threading.Thread(target=run.memory_cap_note, args=(self.run_dir, log))
                  for _ in range(2)]
        for thread in ending:
            thread.start()
        for thread in ending:
            thread.join()
        self.assertEqual(self.lines, [HIT])

    def test_new_code_in_the_same_scope_says_no_kill_twice(self):
        # `pickup_new_code` execs a new interpreter with this environment in the same scope
        self.kills(1)
        run.memory_cap_note(self.run_dir, self.lines.append)
        self.assertEqual(self.lines, [HIT])
        after_exec = (
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "from agentkit import orch, run\n"
            f"orch.OWN_CGROUP = Path({str(self.root / 'own-cgroup')!r})\n"
            f"orch.CGROUP_ROOT = Path({str(self.root / 'cgroup')!r})\n"
            f"run.memory_cap_note(Path({str(self.run_dir)!r}), print)\n")
        for count, said in ((1, ""), (2, HIT + "\n")):
            self.kills(count)
            child = subprocess.run([sys.executable, "-c", after_exec], capture_output=True,
                                   text=True, env=dict(os.environ), timeout=60)
            self.assertEqual((child.returncode, child.stdout), (0, said), child.stderr)

    def test_a_run_from_a_seat_shell_logs_no_kill_of_the_seat(self):
        (self.root / "own-cgroup").write_text(
            "0::/user.slice/user-1000.slice/user@1000.service/agentkit-test.slice/"
            "agentkit-seat-acme.scope\n")
        self.kills(1)
        run.memory_cap_note(self.run_dir, self.lines.append)
        self.assertEqual(self.lines, [])

    def test_a_dead_loop_in_a_scope_that_goes_on_is_no_memory_cap_death(self):
        # the kill ended one process; a loop that died later died of something else,
        # and the dead-loop pass resumes it like any other
        self.kills(2)
        state = run.read_state(self.run_dir)
        for policy, reason in (("continue", None), ("stop", "killed: memory cap 4 GB")):
            with patch.object(run, "_systemctl_fields",
                              return_value=("success", f"/{CGROUP}", policy)):
                self.assertEqual(run.memory_cap_reason(state), reason, policy)


if __name__ == "__main__":
    unittest.main()

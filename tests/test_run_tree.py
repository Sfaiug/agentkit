"""A run ends every process it started, however detached it became.

On 2026-09-20 an executor's test survived three kills of the executor and grew
to 21 GB, because each shell command ran as its own session leader and
`os.killpg` on the worker's group never reached it. So every process of a run
carries AGENTKIT_RUN=<id>, and the run's end -- like every killed turn, every
retry and every finished done-when gate -- stops the run's scope and then every
process carrying the marker, found by scanning /proc/*/environ. Never only a
process group.

Stdlib only, no harness calls, no tmux, no real systemd: the scope stop is a
fake systemctl on PATH or a patched stop, and every sleeper gets a SIGKILL
safety net so a failing test never leaves one behind.
"""

from contextlib import ExitStack
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, worker


def fresh_id():
    """A marker no other run -- and no other test -- can be carrying."""
    return f"test-run-tree-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def wait_gone(pid, timeout=5):
    """True once that pid is gone or a zombie; zombies are the parent's to reap."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        if state in ("Z", "X"):
            return True
        time.sleep(0.05)
    return False


class RunTree(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="run-tree-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run_id = fresh_id()

    def spawn_marked(self, *argv, marker=None):
        """Start a child carrying the run's marker, with a SIGKILL safety net."""
        proc = subprocess.Popen(
            list(argv), start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "AGENTKIT_RUN": self.run_id if marker is None else marker})
        self.addCleanup(self._reap, proc)
        return proc

    @staticmethod
    def _reap(proc):
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass

    @staticmethod
    def sleepers():
        """Every `sleep 100` on the host: the argv every sleeper here is started with."""
        found = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                raw = Path(f"/proc/{entry}/cmdline").read_bytes()
            except OSError:
                continue
            if raw == b"sleep\x00100\x00":
                found.append(int(entry))
        return found

    def enter_run_context(self):
        """Run this test's turns and gates as this run, the way run_slot would."""
        had = hasattr(run._RUN_CONTEXT, "state")
        before = getattr(run._RUN_CONTEXT, "state", None)
        run._RUN_CONTEXT.state = {"run_id": self.run_id, "run_depth": 0}

        def restore():
            if had:
                run._RUN_CONTEXT.state = before
            else:
                try:
                    del run._RUN_CONTEXT.state
                except AttributeError:
                    pass

        self.addCleanup(restore)

    def test_setsid_child_dies_with_the_run(self):
        # The goal's integration case in a throwaway slice: a fake executor starts
        # `setsid sleep` and ends, and ending the run stops the run's scope and
        # leaves no marked process behind. The scope stop is a fake systemctl.
        fake = self.root / "bin"
        fake.mkdir()
        calls = self.root / "systemctl-argv.txt"
        (fake / "systemctl").write_text('#!/bin/sh\nprintf "%s\\n" "$@" >>"$FAKE_CALLS"\n')
        (fake / "systemctl").chmod(0o755)
        self.spawn_marked("setsid", "sleep", "100")
        time.sleep(0.5)
        found = worker.marked_pids(self.run_id)
        self.assertTrue(found)  # the detached sleeper is found by marker before the end
        state = {"run_id": self.run_id, "scope": f"agentkit-run-{self.run_id}"}
        with patch.dict(os.environ, {"PATH": f"{fake}:{os.environ['PATH']}",
                                     "FAKE_CALLS": str(calls)}), \
                patch.object(orch, "user_manager", return_value=True), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            run.stop_run_tree(state, log=lambda _: None)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not calls.exists():
            time.sleep(0.05)
        argv = calls.read_text().split()
        self.assertIn("stop", argv)
        self.assertIn(f"agentkit-run-{self.run_id}.scope", argv)
        self.assertEqual(worker.marked_pids(self.run_id), [])
        for pid in found:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the run")

    def test_marker_scan_finds_a_detached_child_without_systemd(self):
        # No manager on this host: the run still ends what it started, by marker,
        # and a neighbour run's child -- whose marker extends this one's -- survives.
        self.spawn_marked("setsid", "sleep", "100")
        other = self.spawn_marked("sleep", "100", marker=self.run_id + "-other")
        time.sleep(0.5)
        with patch.object(orch, "user_manager", return_value=False):
            found = worker.marked_pids(self.run_id)
            self.assertTrue(found)
            self.assertNotIn(other.pid, found)
            run.stop_run_tree({"run_id": self.run_id, "scope": "none",
                               "scope_reason": "no user systemd manager"},
                              log=lambda _: None)
        for pid in found:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the run")
        try:
            os.kill(other.pid, 0)
        except OSError:
            self.fail("the marker sweep took a process of another run")

    def test_retry_leaves_no_children_of_the_previous_attempt(self):
        # The first attempt fails on the provider after leaving a detached child;
        # the retry on the same run leaves none of it behind.
        cfg = {"models": {"w": {"harness": "claude", "model": "m", "effort": "e",
                                "provider": "p"}},
               "providers": {"p": {}}}
        calls = []

        def attempt(cfg_, name, body, workspace, out_dir, role="executor", session=None,
                    env=None, limit=None):
            calls.append(env.get("AGENTKIT_RUN"))
            if len(calls) == 1:
                survivor = subprocess.Popen(
                    ["setsid", "sleep", "100"], start_new_session=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env=env)
                self.addCleanup(self._reap, survivor)
                time.sleep(0.5)
                left = worker.marked_pids(self.run_id)
                self.assertTrue(left)  # the failed attempt really left one behind
                calls.append(left)
                return 1, "API Error: the backend broke", None, False
            return 0, "## Summary\nall done", None, False

        self.enter_run_context()
        with patch.object(worker, "call", side_effect=attempt), \
                patch.object(run, "TRANSIENT_BACKOFF", (0, 0)):
            code, _, _, dead = run.call_retrying(
                cfg, "w", "do the thing", self.root, self.root / "out",
                "executor", None, lambda _: None)
        self.assertEqual(code, 0)
        self.assertFalse(dead)
        self.assertEqual(calls[0], self.run_id)
        for pid in calls[1]:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the retry")
        self.assertEqual(worker.marked_pids(self.run_id), [])

    def test_done_when_command_children_die_with_the_round(self):
        # A gate command that backgrounds a detached sleeper and exits 0: the
        # sleeper proves it started by writing kid.ready, and dies with the gate.
        # The `sleep 100` scan on both sides proves nothing leaked unmarked either.
        self.assertEqual(self.sleepers(), [])
        self.enter_run_context()
        ok, text = run.run_done_when(
            ["setsid bash -c 'echo started >kid.ready; exec sleep 100' "
             "</dev/null >/dev/null 2>&1 &",
             "for i in $(seq 1 100); do test -f kid.ready && break; sleep 0.1; done; "
             "test -f kid.ready"],
            self.root, self.root / "donewhen.log", set(), limit=60, silence=60)
        self.assertTrue(ok, text)
        self.assertTrue((self.root / "kid.ready").exists())
        self.assertEqual(worker.marked_pids(self.run_id), [])
        self.assertEqual(self.sleepers(), [])

    def test_marker_is_set_on_every_child(self):
        # Worker turns and done-when gates -- the final check is a gate -- all
        # carry the run's marker in the environment they are started with.
        self.enter_run_context()
        self.assertEqual(run.run_child_env().get("AGENTKIT_RUN"), self.run_id)
        cfg = {"models": {"w": {"harness": "claude", "model": "m", "effort": "e",
                                "provider": "p"}},
               "providers": {"p": {}}}
        seen = {}

        def attempt(cfg_, name, body, workspace, out_dir, role="executor", session=None,
                    env=None, limit=None):
            seen["worker"] = (env or {}).get("AGENTKIT_RUN")
            return 0, "## Summary\nall done", None, False

        with patch.object(worker, "call", side_effect=attempt):
            run.call_retrying(cfg, "w", "do the thing", self.root, self.root / "out",
                              "executor", None, lambda _: None)
        self.assertEqual(seen.get("worker"), self.run_id)

        def gate(cmd, limit, **kwargs):
            seen["gate"] = (kwargs.get("env") or {}).get("AGENTKIT_RUN")
            return 0, "", False

        with patch.object(worker, "limited", side_effect=gate):
            ok, _ = run.run_done_when(["true"], self.root, self.root / "dw.log", set())
        self.assertTrue(ok)
        self.assertEqual(seen.get("gate"), self.run_id)

    def test_merge_marks_and_stops_its_delivery_tree(self):
        # `ak run merge` delivers outside run_slot, but its fixer turns and gates
        # still carry the run's marker, and what they started dies with the retry.
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        rid = f"merge-{self.run_id}"
        directory = config.RUNS / rid
        directory.mkdir(parents=True)
        (directory / "task.md").write_text("# Merge\n\n## Done when\n```bash\ntrue\n```\n")
        wt = self.root / "worktree"
        wt.mkdir()
        receipt = {"run_id": rid, "title": "merge fixture", "state": "pass", "verdict": "PASS",
                   "executor": "opus", "reviewer": "astra", "rounds": 1,
                   "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                        "summary": "ok"}],
                   "base": "origin/main", "target": "origin/main", "base_sha": "0" * 40,
                   "branch": "ak/fixture", "worktree": str(wt), "repo": None,
                   "scratch": False, "pr": None, "merge_failed": True,
                   "merge_note": "push rejected", "merged": False, "findings": "",
                   "scope": "none"}
        (directory / "run.json").write_text(json.dumps(receipt))
        seen = {}
        before = getattr(run._RUN_CONTEXT, "state", {})

        def fake_merge(lp):
            seen["marker"] = run.run_child_env().get("AGENTKIT_RUN")
            marked = {"AGENTKIT_RUN": seen["marker"]} if seen["marker"] else {}
            kid = subprocess.Popen(
                ["sleep", "100"], start_new_session=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, **marked})
            self.addCleanup(self._reap, kid)
            time.sleep(0.5)
            seen["kid"] = worker.marked_pids(rid)
            self.assertTrue(seen["kid"])  # the delivery really left one behind
            return True

        with patch.object(config, "load", return_value={}), \
                patch.object(run, "review_pass", return_value=True), \
                patch.object(run, "require_review_pass"), \
                patch.object(run, "merge", side_effect=fake_merge), \
                patch.object(run, "finish", return_value=0) as done:
            self.assertEqual(run.cmd_merge([rid]), 0)
        self.assertEqual(seen.get("marker"), rid)
        self.assertEqual(done.call_count, 1)
        for pid in seen["kid"]:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the delivery retry")
        self.assertEqual(worker.marked_pids(rid), [])
        self.assertEqual(getattr(run._RUN_CONTEXT, "state", {}), before)

    def test_reap_stops_an_ended_run_whose_loop_died(self):
        # The loop recorded its ending and died before its final cleanup: the
        # first reap ends what it left behind and stamps the receipt, so the
        # second reap has nothing left to sweep.
        for status, extra in (("pass", {}), ("exhausted", {"quota_dry": True})):
            with self.subTest(status=status):
                rid = f"reap-{self.run_id}-{status}"
                directory = self.root / rid
                directory.mkdir()
                receipt = {"run_id": rid, "title": "reap fixture", "state": status,
                           "pid": 999999, "scope": "none", **extra}
                (directory / "run.json").write_text(json.dumps(receipt))
                kid = subprocess.Popen(
                    ["setsid", "sleep", "100"], start_new_session=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, "AGENTKIT_RUN": rid})
                self.addCleanup(self._reap, kid)
                time.sleep(0.5)
                found = worker.marked_pids(rid)
                self.assertTrue(found)
                with patch.object(worker, "kill_marked",
                                  wraps=worker.kill_marked) as swept:
                    run.reap(directory, dict(receipt))
                    run.reap(directory, dict(receipt))
                self.assertEqual(swept.call_count, 1)
                for pid in found:
                    self.assertTrue(wait_gone(pid), f"{pid} outlived the reaped run")
                saved = json.loads((directory / "run.json").read_text())
                self.assertEqual(saved["tree_stopped"], [999999, None])

    def _fake_adapter(self):
        script = self.root / "fake-adapter.sh"
        seen = self.root / "adapter-seen.txt"
        script.write_text(
            "#!/bin/sh\n"
            'echo "marker=${AGENTKIT_RUN-unset}" >>"$FAKE_SEEN"\n'
            'if [ -n "$AGENTKIT_RUN" ]; then setsid sleep 100 </dev/null >/dev/null 2>&1 & fi\n'
            'echo "fake adapter holds a token"\n')
        script.chmod(0o755)
        return script, seen

    def test_auth_probe_carries_the_run_marker(self):
        # A probe the loop runs is the run's own: the adapter sees the marker, its
        # detached descendants inherit it, and the sweep can end them. A probe with
        # no run to name -- the tick's login watch -- runs unmarked, as before.
        script, seen = self._fake_adapter()
        with patch.dict(os.environ, {"FAKE_SEEN": str(seen)}), \
                patch.object(config, "adapter", return_value=script):
            self.assertEqual(worker.auth_ok("claude"), (True, "fake adapter holds a token"))
            self.assertEqual(seen.read_text().split(), ["marker=unset"])
            self.assertTrue(worker.auth_ok("claude", run_id=self.run_id)[0])
        self.assertIn(f"marker={self.run_id}", seen.read_text().split())
        time.sleep(0.5)
        found = worker.marked_pids(self.run_id)
        self.assertTrue(found)
        self.assertTrue(worker.kill_marked(self.run_id))
        for pid in found:
            self.assertTrue(wait_gone(pid))

    def test_worker_call_marks_its_auth_probes(self):
        # Both auth probes of a turn -- before the launch and after a silence --
        # carry the turn's marker, so their descendants die with the run.
        script, seen = self._fake_adapter()
        cfg = {"models": {"w": {"harness": "claude", "model": "m", "effort": "e",
                                "provider": "p"}},
               "providers": {"p": {}}}
        with patch.dict(os.environ, {"FAKE_SEEN": str(seen)}), \
                patch.object(config, "adapter", return_value=script), \
                patch.object(worker, "limited", return_value=(0, "", False)):
            code, _, _, killed = worker.call(
                cfg, "w", "do the thing", self.root, self.root / "call-out", "executor",
                None, env={**os.environ, "AGENTKIT_RUN": self.run_id}, limit=60)
        self.assertEqual(code, 0)
        self.assertFalse(killed)
        lines = seen.read_text().split()
        self.assertTrue(lines)  # the turn probed at least once
        self.assertTrue(all(line == f"marker={self.run_id}" for line in lines), lines)
        self.assertTrue(worker.kill_marked(self.run_id))
        self.assertEqual(worker.marked_pids(self.run_id), [])

    def test_tool_env_marks_run_owned_helpers(self):
        # git and gh the loop runs carry the run's marker, so detached or
        # timeout-surviving descendants are the run's to end. Outside a run,
        # helpers stay unmarked.
        saved = os.environ.pop("AGENTKIT_RUN", None)
        try:
            self.assertNotIn("AGENTKIT_RUN", run.tool_env())
        finally:
            if saved is not None:
                os.environ["AGENTKIT_RUN"] = saved
        self.enter_run_context()
        self.assertEqual(run.tool_env().get("AGENTKIT_RUN"), self.run_id)
        code, _, _ = run.tool_run(
            ["bash", "-c", "setsid sleep 100 </dev/null >/dev/null 2>&1 &"])
        self.assertEqual(code, 0)
        time.sleep(0.5)
        found = worker.marked_pids(self.run_id)
        self.assertTrue(found)
        self.assertTrue(worker.kill_marked(self.run_id))
        for pid in found:
            self.assertTrue(wait_gone(pid))

    def _leave_marked_sleep(self, left):
        kid = subprocess.Popen(
            ["setsid", "sleep", "100"], start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "AGENTKIT_RUN": self.run_id})
        self.addCleanup(self._reap, kid)
        time.sleep(0.5)
        found = worker.marked_pids(self.run_id)
        self.assertTrue(found)  # the silent turn really left one behind
        left.extend(found)

    def _no_verdict_case(self, foreground):
        case = self.root / ("foreground" if foreground else "plain")
        round_dir = case / "round-1"
        round_dir.mkdir(parents=True)
        if foreground:
            (round_dir / "reviewer-foreground").mkdir()
        wt = case / "wt"
        wt.mkdir()
        cfg = {"models": {
            "exec": {"harness": "claude", "model": "m", "effort": "e", "provider": "pa"},
            "rev": {"harness": "claude", "model": "m", "effort": "e", "provider": "pb"},
            "spare": {"harness": "claude", "model": "m", "effort": "e", "provider": "pc"}},
            "providers": {"pa": {}, "pb": {}, "pc": {}}}
        lp = SimpleNamespace(
            cfg=cfg, run_dir=case, state={"run_id": self.run_id, "round_summaries": []},
            wt=wt, body="task", cmds=["true"], reviewer="rev", executor="exec",
            spares=["spare"], rnd=1, round_dir=round_dir, scratch=True, findings="",
            review_sid=None,
            log=lambda message: None, turn_limit=60, save=lambda: None,
            role=lambda name: name, dir=lambda name: round_dir / name)
        left, calls = [], []

        def attempt(cfg_, name, body, workspace, out_dir, role, session, log, limit=None):
            calls.append(name)
            if len(calls) == 1:
                self._leave_marked_sleep(left)
                return 0, "rambling at length but never judging anything", None, False
            return 0, "## Findings\nnone\n\nVERDICT: PASS", None, False

        def second_ask(cfg_, name, text, workspace, out_dir, role="executor", session=None,
                       env=None, limit=None):
            self.assertEqual((env or {}).get("AGENTKIT_RUN"), self.run_id)
            self._leave_marked_sleep(left)
            return 0, "still rambling, still no verdict", None, False

        if foreground:
            direct = AssertionError("the extra ask was already spent")
        else:
            direct = second_ask
        with patch.object(run, "call_retrying", side_effect=attempt), \
                patch.object(worker, "call", side_effect=direct), \
                patch.object(run, "collect_usage", return_value={}), \
                patch.object(run.usage, "pick_order", return_value=["spare"]):
            self.assertEqual(run.review(lp, "did stuff", True, "$ true\n[exit 0]"), "PASS")
        self.assertEqual(calls, ["rev", "spare"])
        for pid in left:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the reviewer fallback")
        self.assertEqual(worker.marked_pids(self.run_id), [])

    def test_no_verdict_fallback_leaves_no_children(self):
        # A reviewer that never gives a verdict falls back to a spare; the silent
        # turn's detached children die with it -- whether the silence needed the
        # extra ask or had already spent it finishing background work.
        self.enter_run_context()
        for foreground in (False, True):
            with self.subTest(foreground=foreground):
                self._no_verdict_case(foreground)

    def test_killed_turn_takes_its_detached_children(self):
        # A turn killed at its ceiling ends the setsid child with it, not only
        # its process group; the watcher proves the child was alive mid-turn.
        log = self.root / "activity.log"
        log.write_text("")
        alive, stop = [], threading.Event()

        def watch():
            while not stop.is_set():
                alive.extend(worker.marked_pids(self.run_id))
                time.sleep(0.05)

        watcher = threading.Thread(target=watch)
        watcher.start()
        try:
            code, _, killed = worker.limited(
                ["bash", "-c", "setsid sleep 100 </dev/null >/dev/null 2>&1 & "
                               "exec sleep 30"],
                2, activity=log, stdin=subprocess.DEVNULL,
                env={**os.environ, "AGENTKIT_RUN": self.run_id})
        finally:
            stop.set()
            watcher.join()
        self.assertEqual(code, worker.TIMEOUT)
        self.assertTrue(killed)
        self.assertTrue(alive, "the detached child was never observed mid-turn")
        self.assertEqual(worker.marked_pids(self.run_id), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

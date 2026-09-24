"""v5x: nothing stays stuck -- a silent run is recovered by the tick, by itself.

Offline and deterministic: fake run directories under a temporary HOME with fake
`ak run` processes (a `sleep` that spawns a child holding an `flock`). No tmux
beyond `agentkit-test`, no webhook, no model calls.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, watch

TASK = """---
rounds: 3
---
# Do the thing

## Goal
Do it.

## Constraints
- None.

## Done when
```bash
bash tests/smoke.sh
```
"""

TASK_SLOW = """---
rounds: 3
stall_minutes: 240
---
# Do the slow thing

## Goal
Do it slowly.

## Constraints
- None.

## Done when
```bash
bash tests/smoke.sh
```
"""


def have(cmd):
    return shutil.which(cmd) is not None


class V5X(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5x-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AK_RUN_ROLE": "orchestrator",
            "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": "",
        }))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        # Keep the kill wait short; sleeps die on TERM at once.
        self.stack.enter_context(patch.object(watch, "STALL_KILL_WAIT", 3))
        self.logs = []
        self.resumed = []
        self.typed = []
        self.cards = []
        self.stack.enter_context(patch.object(
            watch, "launch_resume",
            side_effect=lambda run_id, log=lambda _: None: self.resumed.append(run_id) or True))
        self.stack.enter_context(patch.object(
            watch, "type_into",
            side_effect=lambda session, text, log: self.typed.append(
                (session.get("name"), text)) or True))
        self.stack.enter_context(patch.object(
            notify, "shaped",
            side_effect=lambda kind, text, **kw: self.cards.append((kind, text, kw)) or 0))
        self.stack.enter_context(patch.object(run, "launcher_watched", return_value=False))
        self.stack.enter_context(patch.object(orch, "find", return_value=None))
        self.procs = []
        self.addCleanup(self.kill_procs)

    def kill_procs(self):
        for proc in self.procs:
            try:
                # The whole tree at once: killing only the parent would reparent
                # the gate child to init and leave it behind.
                watch.kill_tree(proc.pid, log=lambda _: None)
            except (OSError, ValueError):
                pass
        for proc in self.procs:
            try:
                proc.kill()
            except OSError:
                pass
        for proc in self.procs:
            try:
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.procs = []

    # -- helpers ---------------------------------------------------------
    def spawn_loop(self, child_argv):
        """A fake `ak run` loop: a python parent that spawns one child, then sleeps."""
        parent = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess,sys,time; "
             "subprocess.Popen(sys.argv[1:]); time.sleep(1000)",
             *child_argv],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(parent)
        # Let the child appear under the parent before the tick reads /proc.
        for _ in range(100):
            if watch.loop_children(parent.pid):
                break
            time.sleep(0.05)
        return parent

    def spawn_worker(self, reviewer=False):
        """A fake loop whose child is a worker turn: argv[0] is an adapter script.

        The spawner execs the interpreter itself under the chosen argv, so /proc
        keeps the step's shape -- the adapter path, and a reviewer's out-dir --
        while the process just sleeps until the tick stops it. (Exec'ing a script
        file would not do: the kernel replaces argv[0] with its interpreter.)
        """
        ad = self.root / "adapters"
        ad.mkdir(exist_ok=True)
        out = "out/round-2/reviewer" if reviewer else "out/executor"
        step = [str(ad / "fake.sh"), "-c", "import time; time.sleep(1000)", out]
        parent = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess,sys,time; "
             "subprocess.Popen(sys.argv[1:], executable=sys.executable); time.sleep(1000)",
             *step],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(parent)
        for _ in range(100):
            if watch.loop_children(parent.pid):
                break
            time.sleep(0.05)
        return parent

    def gate_child(self):
        lock = str(self.root / f"v5x-{time.time_ns()}.lock")
        if have("flock"):
            return ["flock", lock, "sleep", "1000"]
        return ["sleep", "1000"]



    def make_run(self, run_id, *, stalls=None, task_text=TASK, minutes=None,
                 pid=None, executor="opus", reviewer="astra", seat=None):
        run_dir = config.RUNS / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "task.md").write_text(task_text)
        (run_dir / "log.txt").write_text("[00:00:00] run started\n")
        rnd = run_dir / "round-1"
        rnd.mkdir(exist_ok=True)
        (rnd / "donewhen.log").write_text("gate output\n")
        state = {"run_id": run_id, "title": "Do the thing", "task": str(run_dir / "task.md"),
                 "launched_session": seat, "repo": None, "scratch": True,
                 "base": None, "target": None, "base_sha": None, "branch": None,
                 "worktree": str(self.root / "work" / run_id),
                 "executor": executor, "reviewer": reviewer, "rounds": 3,
                 "state": "running", "verdict": None,
                 "started_at": time.time() - 3700, "finished_at": None,
                 "round_summaries": [{"round": 1, "verdict": "FAIL", "done_when": False,
                                      "summary": "first try"}],
                 "findings": "", "merge_method": "squash", "no_merge": True,
                 "pr": None, "merged": False, "merge_note": None, "reported": False,
                 "stalls": list(stalls or [])}
        if minutes is not None:
            state["stall_minutes"] = minutes
        if pid is not None:
            state.update(run.process_owner(pid))
        else:
            state["pid"] = 2 ** 30
        (run_dir / "run.json").write_text(json.dumps(state, indent=2))
        return run_dir, state

    def age_run(self, run_dir, minutes):
        old = time.time() - minutes * 60
        for root, _, files in os.walk(run_dir):
            for name in files:
                try:
                    os.utime(Path(root, name), (old, old))
                except OSError:
                    pass

    def read_state(self, run_dir):
        return json.loads((run_dir / "run.json").read_text())

    def child_pids(self, pid):
        return [child for child, _ in watch.loop_children(pid)]

    def test_v5x_first_stall_kills_step_not_loop(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run("20260916-0000-v5x-first", pid=parent.pid)
        children = self.child_pids(parent.pid)
        self.assertTrue(children, "fake loop should have a gate child")
        grandchild = watch.descendants(children[0])
        self.age_run(run_dir, 61)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 1)
        entry = state["stalls"][0]
        self.assertEqual(entry["action"], "killed step")
        self.assertEqual(entry["round"], 2)
        self.assertIn("done-when", entry["step"])
        text = (run_dir / "log.txt").read_text()
        self.assertIn("stall:", text)
        self.assertIn("no output for 20 min in round 2", text)
        for member in grandchild:
            self.assertTrue(watch._gone(member), f"{member} should be gone")
        self.assertFalse(watch._gone(parent.pid), "the loop itself must live on")
        self.assertEqual(self.resumed, [])
        self.assertEqual(self.typed, [])
        self.assertEqual(self.cards, [])

    def test_v5x_silent_19min_untouched(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run("20260916-0000-v5x-quiet", pid=parent.pid)
        children = self.child_pids(parent.pid)
        self.assertTrue(children)
        self.age_run(run_dir, 19)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(state.get("stalls") or [], [])
        self.assertNotIn("stall:", (run_dir / "log.txt").read_text())
        self.assertFalse(watch._gone(children[0]), "a quiet run is never touched")
        self.assertFalse(watch._gone(parent.pid))
        self.assertEqual(self.resumed, [])

    def test_v5x_stall_minutes_240_ignored_at_21(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run("20260916-0000-v5x-slow", pid=parent.pid,
                                   task_text=TASK_SLOW)
        self.age_run(run_dir, 21)
        self.assertEqual(run.stall_minutes_for(run_dir, self.read_state(run_dir)), 20)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state["stalls"]), 1)
        self.assertIn("stall:", (run_dir / "log.txt").read_text())
        self.assertFalse(watch._gone(parent.pid))
        self.assertEqual(self.resumed, [])

    def test_v5x_second_stall_stops_loop_and_resumes(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-second",
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "killed step"}],
            pid=parent.pid)
        self.age_run(run_dir, 61)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 2)
        self.assertIn("resumed", state["stalls"][-1]["action"])
        self.assertIn("stall:", (run_dir / "log.txt").read_text())
        self.assertTrue(watch._gone(parent.pid), "the loop is stopped before resume")
        self.assertEqual(self.resumed, [run_dir.name])
        # A done-when stall hands nothing over.
        self.assertEqual(state.get("executor"), "opus")
        self.assertEqual(state.get("executor_history") or [], [])
        # The killed loop stays `running` for its ordered resume: reap must not
        # interrupt it, and nobody is told (that waits for rung three).
        self.assertIn("stall_resume_at", state)
        reaped = run.reap(run_dir, dict(state))
        self.assertEqual(reaped["state"], "running")
        self.assertEqual(self.typed, [])
        self.assertEqual(self.cards, [])

    def test_v5x_third_stall_parks_and_types_into_launching_seat(self):
        parent = self.spawn_loop(self.gate_child())
        with patch.object(run, "launcher_watched", return_value=True), \
                patch.object(orch, "find", return_value={"name": "seat1"}):
            run_dir, _ = self.make_run(
                "20260916-0000-v5x-third",
                stalls=[{"time": time.time() - 7200, "round": 2,
                         "step": "done-when: bash tests/smoke.sh", "action": "killed step"},
                        {"time": time.time() - 3600, "round": 2,
                         "step": "done-when: bash tests/smoke.sh", "action": "resumed"}],
                pid=parent.pid, seat="seat1")
            self.age_run(run_dir, 61)
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(state.get("state"), "stalled")
        self.assertEqual(state["stalls"][-1]["action"], "parked")
        self.assertTrue(state.get("stalled_notified"), "a told seat records its notice")
        self.assertIn("stall:", (run_dir / "log.txt").read_text())
        self.assertEqual(run.continue_line(state), f"continue: ak run resume {run_dir.name}")
        self.assertIn(f"ak run resume {run_dir.name}", (run_dir / "result.md").read_text())
        self.assertEqual(len(self.typed), 1)
        seat, line = self.typed[0]
        self.assertEqual(seat, "seat1")
        self.assertIn(run_dir.name, line)
        self.assertIn("stalled three times", line)
        self.assertIn(f"ak run resume {run_dir.name}", line)
        self.assertEqual(self.cards, [], "a live seat is typed into, never carded")
        self.assertEqual(self.resumed, [])

    def test_v5x_third_stall_without_seat_sends_one_card(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-noseat",
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "killed step"},
                    {"time": time.time() - 3600, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "resumed"}],
            pid=parent.pid, seat=None)
        self.age_run(run_dir, 61)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(state.get("state"), "stalled")
        self.assertTrue(state.get("stalled_notified"), "a sent card records its notice")
        self.assertEqual(len(self.cards), 1, "one card, and nothing before rung three")
        kind, text, kw = self.cards[0]
        self.assertEqual(kind, "needs")
        self.assertIn(run_dir.name, text)
        self.assertIn("parked", text)
        self.assertEqual(self.typed, [])

    def test_v5x_dead_pid_resumed_at_once(self):
        run_dir, _ = self.make_run("20260916-0000-v5x-dead", pid=2 ** 30)
        self.age_run(run_dir, 61)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 1)
        self.assertIn("resumed", state["stalls"][-1]["action"])
        self.assertIn("stall:", (run_dir / "log.txt").read_text())
        self.assertEqual(self.resumed, [run_dir.name])

    def test_v5x_worker_stall_records_executor_history(self):
        parent = self.spawn_worker()
        children = self.child_pids(parent.pid)
        self.assertTrue(children, "fake loop should have a worker child")
        cfg = {"models": {"opus": {"harness": "claude", "model": "m",
                                   "effort": "e", "provider": "anthropic"},
                          "astra": {"harness": "codex", "model": "m",
                                    "effort": "e", "provider": "openai"}},
               "tiers": {"A": ["opus"], "B": ["opus", "astra"]},
               "providers": {"anthropic": {}, "openai": {}}}
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-handover",
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "worker: opus", "action": "killed step"}],
            pid=parent.pid, executor="opus")
        self.age_run(run_dir, 61)
        with patch("agentkit.usage.collect", return_value={}), \
                patch("agentkit.usage.pick_order", return_value=["astra", "opus"]):
            watch.recover_runs(cfg, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 2)
        self.assertIn("handover", state["stalls"][-1]["action"])
        self.assertEqual(state.get("executor"), "astra")
        history = state.get("executor_history") or []
        self.assertTrue(history, "a worker stall hands the turn over with history")
        self.assertEqual(history[-1]["reason"], "stalled")
        self.assertEqual(history[-1]["from"], "opus")
        self.assertEqual(history[-1]["to"], "astra")
        self.assertEqual(self.resumed, [run_dir.name])

    def test_v5x_status_renders_counts(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-status",
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "killed step"},
                    {"time": time.time() - 3600, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "resumed"}],
            pid=parent.pid)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([run_dir.name]), 0)
        self.assertIn("stalled 2× (done-when: bash tests/smoke.sh), recovered", out.getvalue())
        parked_dir, _ = self.make_run("20260916-0000-v5x-parked", pid=2 ** 30)
        parked = self.read_state(parked_dir)
        run.park_stalled(parked_dir, parked,
                         {"time": time.time(), "round": 2,
                          "step": "done-when: bash tests/smoke.sh", "action": "parked"})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([parked_dir.name]), 0)
        body = out.getvalue()
        # A parked run resumes itself, so it is still working; the note says what for.
        self.assertIn("● working", body)
        self.assertIn(f"continue: ak run resume {parked_dir.name}", body)

    def test_v5x_menu_words_for_silent_and_stalled(self):
        from agentkit import terminal
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-menu", pid=2 ** 30,
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "done-when: bash tests/smoke.sh", "action": "killed step"}])
        self.age_run(run_dir, 120)
        state = self.read_state(run_dir)
        _, _, word, _ = menu.run_progress(state)
        self.assertTrue(word.startswith("silent "), word)
        self.assertIn("2h", word)
        # The words have to survive the paths that render them: the rollup
        # (STATE_ORDER) and the coloured draws (STATE_STYLES), plain and coloured.
        # No run ever makes a project now.
        groups = menu.projects({}, [])
        self.assertEqual(groups, [])
        for words in (menu.run_style(word), menu.run_style("interrupted")):
            self.assertIn(words, menu.STATE_ORDER)
            self.assertIn(words, terminal.STATE_STYLES)
        with patch.object(terminal, "colour_depth", return_value=24):
            menu.project_run(run_dir, state, 100)
            for group in groups:
                menu.project_header(group, 100)
            menu.run_row(1, run_dir, state)
        # Progress since the stall reads working again, while the status keeps
        # the recovered counts.
        (run_dir / "round-1" / "worker-note.txt").write_text("the fixer wrote back\n")
        _, _, word, _ = menu.run_progress(self.read_state(run_dir))
        self.assertEqual(word, "working")
        parked = dict(state, state="stalled")
        self.assertEqual(menu.run_progress(parked)[2], "stalled")
        self.assertEqual(menu.run_style("stalled"), "needs you")
        with patch.object(terminal, "colour_depth", return_value=24):
            menu.project_run(run_dir, parked, 100)

    def test_v5x_only_argv0_names_a_worker_turn(self):
        cfg = {"models": {"m": {"harness": "fakeharness", "model": "m",
                                "effort": "e", "provider": "p"}}}
        # A gate's own text may name roles, adapters and harnesses freely.
        self.assertFalse(watch.is_worker_cmd(
            ["bash", "-c", "grep -q worker adapters/fakeharness.sh"], cfg))
        self.assertFalse(watch.is_worker_cmd(
            ["bash", "-c", "pytest tests/test_worker_pool.py"], cfg))
        self.assertFalse(watch.is_worker_cmd(["sleep", "1000"], cfg))
        # The executable itself is what counts: an adapter path, or the cfg
        # harness in its basename.
        self.assertTrue(watch.is_worker_cmd(
            ["/r/adapters/fakeharness.sh", "run", "m", "e", "w", "p", "o"], cfg))
        self.assertTrue(watch.is_worker_cmd(["/opt/x/fakeharness", "run"], cfg))
        self.assertTrue(watch.is_worker_cmd(["/r/adapters/other.sh"], None))

    def test_v5x_second_stall_on_reviewer_resumes_without_handover(self):
        parent = self.spawn_worker(reviewer=True)
        children = self.child_pids(parent.pid)
        self.assertTrue(children, "fake loop should have a reviewer child")
        run_dir, _ = self.make_run(
            "20260916-0000-v5x-reviewer",
            stalls=[{"time": time.time() - 7200, "round": 2,
                     "step": "reviewer: astra", "action": "killed step"}],
            pid=parent.pid, executor="opus", reviewer="astra")
        self.age_run(run_dir, 61)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 2)
        self.assertIn("reviewer: astra", state["stalls"][-1]["step"])
        self.assertIn("resumed", state["stalls"][-1]["action"])
        self.assertNotIn("handover", state["stalls"][-1]["action"])
        # The stuck reviewer is the loop's own fallback to replace, not the executor.
        self.assertEqual(state.get("executor"), "opus")
        self.assertEqual(state.get("executor_history") or [], [])
        self.assertEqual(self.resumed, [run_dir.name])

    def test_v5x_park_notice_retried_until_accepted(self):
        run_dir, _ = self.make_run("20260916-0000-v5x-retry", pid=2 ** 30,
                                   seat=None)
        parked = self.read_state(run_dir)
        run.park_stalled(run_dir, parked,
                         {"time": time.time() - 3700, "round": 2,
                          "step": "done-when: bash tests/smoke.sh", "action": "parked"})
        self.assertFalse(self.read_state(run_dir).get("stalled_notified"))
        with patch.object(notify, "shaped",
                          side_effect=lambda *a, **k: self.cards.append(a) or 1):
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        self.assertEqual(len(self.cards), 1)
        self.assertFalse(self.read_state(run_dir).get("stalled_notified"))
        self.assertTrue(any("later tick" in line for line in self.logs),
                        "the log must promise a retry, and mean it")
        with patch.object(notify, "shaped",
                          side_effect=lambda *a, **k: self.cards.append(a) or 0):
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        self.assertEqual(len(self.cards), 2)
        self.assertTrue(self.read_state(run_dir).get("stalled_notified"))
        # Delivered once: no third attempt.
        with patch.object(notify, "shaped",
                          side_effect=lambda *a, **k: self.cards.append(a) or 0):
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        self.assertEqual(len(self.cards), 2)

    def test_v5x_first_stall_kills_the_identified_step(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, _ = self.make_run("20260916-0000-v5x-identified", pid=parent.pid)
        children = self.child_pids(parent.pid)
        self.assertTrue(children)
        self.age_run(run_dir, 61)
        seen = {}
        real_kill = watch.kill_tree

        def capture(pid, log=lambda _: None):
            seen["pid"] = pid
            return real_kill(pid, log)

        with patch.object(watch, "kill_tree", side_effect=capture):
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        self.assertEqual(seen.get("pid"), children[0],
                         "rung one stops the child the step was read off, not a re-scan")
        self.assertTrue(watch._gone(children[0]))
        self.assertFalse(watch._gone(parent.pid))

    def test_v5x_first_stall_with_scope_keeps_scope_alive(self):
        parent = self.spawn_loop(self.gate_child())
        run_dir, state = self.make_run("20260916-0000-v5x-scoped-first", pid=parent.pid)
        state["scope"] = "agentkit-run-20260916-0000-v5x-scoped-first"
        run.save_state(run_dir, state)
        children = self.child_pids(parent.pid)
        self.assertTrue(children)
        self.age_run(run_dir, 61)
        with patch.object(orch, "stop_scope", return_value=True) as stop:
            watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        stop.assert_not_called()
        self.assertFalse(watch._gone(parent.pid))


if __name__ == "__main__":
    unittest.main(verbosity=2)

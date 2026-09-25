"""Silence stops a run's steps; continuing output buys time, not a fresh ceiling."""

from contextlib import ExitStack, redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, watch, worker
from test_v5j import E2E, SMOKE, lock_argv, lock_program


class Clock:
    """Advance only on the watchdog's ticks, leaving real child processes to run."""

    def __init__(self, step):
        self.owner = threading.current_thread()
        self.step, self.now = step, 0
        self.seen = set()

    def __call__(self):
        current = threading.current_thread()
        if current is not self.owner:
            if current in self.seen:
                self.now += self.step
            self.seen.add(current)
        return self.now


class Silence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".silence-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(patch.stopall)
        # a worker running this file carries its own run's marker, and a silent turn below
        # ends every process marked with the run it inherits
        patch.dict(os.environ, {"AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0"}).start()
        patch.object(run, "dirty_paths", return_value=[]).start()
        patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}).start()

    def command(self, text):
        return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(text)}"

    def gate(self, commands, clock):
        logs = []
        with patch.object(worker.time, "monotonic", side_effect=clock):
            ok, text = run.run_done_when(commands, self.root, self.root / "donewhen.log",
                                         set(), log=logs.append)
        return ok, text, logs

    def adapter(self, body):
        path = self.root / "adapter"
        path.write_text(f"#!{sys.executable}\nimport pathlib, sys, time\n"
                        "out = pathlib.Path(sys.argv[6])\n" + body)
        path.chmod(0o755)
        patch.object(config, "adapter", return_value=path).start()
        return {"providers": {"openai": {}}, "models": {"fixture": {"harness": "codex", "provider": "openai",
                                        "model": "fixture", "effort": "low"}}}

    def test_template_has_no_front_matter_and_parses(self):
        path = REPO / "templates" / "task.md"
        self.assertFalse(path.read_text().startswith("---"))
        meta, body, title = run.parse_task(path)
        self.assertEqual(meta, {})
        self.assertEqual(title, "Title")
        self.assertIn("## Goal", body)
        self.assertIn("## Constraints", body)
        every, once = run.done_when_groups(body, path)
        self.assertTrue(every)
        self.assertEqual(once, ["bash tests/smoke.sh"])

    def test_old_keys_are_ignored_with_one_log_line_each(self):
        task = self.root / "task.md"
        keys = ("done_when_minutes", "turn_hours", "stall_minutes")
        task.write_text("---\n" + "".join(f"{key}: never\n" for key in keys)
                        + "---\n# Compatibility\n")
        meta, _, _ = run.parse_task(task)
        log_path = self.root / "log.txt"

        def log(line):
            with log_path.open("a") as fh:
                fh.write(line + "\n")

        for _ in range(3):
            run.ignore_time_keys(self.root, meta, log)
        for key in keys:
            self.assertEqual(log_path.read_text().count(
                f"ignoring {key}: the loop watches for silence"), 1)

    def test_silent_done_when_is_killed_after_silence_minutes(self):
        cmd = self.command("import time; time.sleep(600)")
        clock = Clock(60 * run.SILENCE_MINUTES / 2)
        ok, text, logs = self.gate([cmd], clock)
        self.assertFalse(ok)
        self.assertGreaterEqual(clock.now, 60 * run.SILENCE_MINUTES)
        self.assertIn("[killed at the limit]", text)
        self.assertEqual(logs, [f"done-when: stopped after 20 min of silence: {cmd} "
                                "(last output: (no output))"])

    def test_silent_command_keeps_its_last_output_line(self):
        cmd = self.command("import time; print('first'); print('last'); time.sleep(600)")
        ok, text, logs = self.gate([cmd], Clock(600))
        self.assertFalse(ok)
        self.assertIn("first\nlast", text)
        self.assertIn(f"{cmd} (last output: last)", logs[0])

    def test_background_child_holding_output_does_not_escape_silence(self):
        child = self.root / "child.pid"
        cmd = f"sleep 600 & echo $! > {shlex.quote(str(child))}"
        ok, text, logs = self.gate([cmd], Clock(600))
        self.assertFalse(ok, text)
        self.assertIn("20 min of silence", logs[0])
        self.assertTrue(watch._gone(int(child.read_text())))

    def test_chatty_command_past_silence_total_is_not_killed(self):
        # No newline: any output counts, and it reaches the gate log before exit.
        cmd = self.command("import time\nfor _ in range(35):\n print('.', end='', flush=True)\n time.sleep(.1)")
        clock = Clock(600)
        ok, text, logs = self.gate([cmd], clock)
        self.assertTrue(ok, text)
        self.assertGreater(clock.now, 60 * run.SILENCE_MINUTES)
        self.assertIn("[exit 0]", text)
        self.assertEqual(logs, [])

    def test_ceiling_kills_a_command_that_prints_forever(self):
        cmd = self.command("import time\nwhile True:\n print('still going', flush=True)\n time.sleep(.05)")
        clock = Clock(3600 * run.CEILING_HOURS / 3)
        ok, text, logs = self.gate([cmd, "echo never"], clock)
        self.assertFalse(ok)
        self.assertGreaterEqual(clock.now, 3600 * run.CEILING_HOURS)
        self.assertIn("6h ceiling", logs[0])
        self.assertIn("last output: still going", logs[0])
        self.assertNotIn("$ echo never", text)

    def test_silent_turn_is_retried_as_transport_death(self):
        cfg = self.adapter(
            "(out / 'events.jsonl').write_text('{\"type\":\"thread.started\",\"thread_id\":\"sid\"}\\n')\n"
            "if len(sys.argv) == 7:\n time.sleep(600)\n"
            "(out / 'final.md').write_text('## Summary\\nFinished')\n")
        logs = []
        # two levels under the sandbox, as a round's out dir sits under its run: the turn reads
        # the run directory as the out dir's grandparent, and one level up here is the checkout
        with patch.object(worker.time, "monotonic", side_effect=Clock(600)), \
                patch.object(run, "TRANSIENT_BACKOFF", (0, 0)):
            code, text, sid, dead = run.call_retrying(
                cfg, "fixture", "do it", self.root, self.root / "turns" / "executor",
                "executor", None, logs.append)
        self.assertEqual((code, sid, dead), (0, "sid", False))
        self.assertIn("Finished", text)
        self.assertTrue(any("emitted no event for 20m" in line and "resuming session sid" in line
                            for line in logs), logs)
        self.assertEqual(sum("retrying in 0s" in line for line in logs), 1)
        self.assertTrue((self.root / "turns" / "executor-retry1" / "final.md").exists())
        self.assertFalse((self.root / "turns" / "executor" / "final.md").exists())

    def test_chatty_turn_has_no_total_cap(self):
        cfg = self.adapter(
            "for _ in range(35):\n"
            " with (out / 'events.jsonl').open('a') as fh: fh.write('{\"type\":\"event\"}\\n')\n"
            " time.sleep(.1)\n"
            "(out / 'final.md').write_text('## Summary\\nFinished')\n")
        clock = Clock(4 * 3600)
        with patch.object(worker.time, "monotonic", side_effect=clock):
            code, text, _, dead = run.call_retrying(
                cfg, "fixture", "do it", self.root, self.root / "turns" / "executor",
                "executor", None, lambda _: None)
        self.assertEqual((code, dead), (0, False))
        self.assertIn("Finished", text)
        self.assertGreater(clock.now, 3600 * run.CEILING_HOURS)

    def test_run_json_records_new_fields_and_removes_old_fields(self):
        state = {"done_when_minutes": 45, "turn_hours": 3, "stall_minutes": 60}
        run.save_state(self.root, state)
        self.assertEqual(json.loads((self.root / "run.json").read_text()),
                         {"silence_minutes": 20, "ceiling_hours": 6})

    def test_resumed_run_keeps_recorded_limits(self):
        state = {"silence_minutes": 17, "ceiling_hours": 5,
                 "base": None, "rounds": 3, "executor": None, "reviewer": None,
                 "round_summaries": [], "scratch": True}
        run.save_state(self.root, state)
        with patch.object(run, "SILENCE_MINUTES", 21), patch.object(run, "CEILING_HOURS", 7):
            saved = run.read_state(self.root)
            run.save_state(self.root, saved)
            lp = run.Loop({}, self.root, saved, {}, lambda _: None, self.root, "", [], "", [])
            self.assertEqual((lp.turn_limit, lp.done_when_limit), (17 * 60, 5 * 3600))
            self.assertEqual(run.stall_minutes_for(self.root, saved), 17)
            self.assertAlmostEqual(watch.stall_allowance(saved, "done-when", 17),
                                   17 + (worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL) / 60)
        self.assertEqual((saved["silence_minutes"], saved["ceiling_hours"]), (17, 5))

    def fast_lock(self, script, path, seconds):
        # Speed up only the reporter in the child. The actual flock, signal timeout,
        # pipe relay and parent watchdog run normally on this private lock.
        body = ("import threading\n"
                "event_wait = threading.Event.wait\n"
                "threading.Event.wait = lambda self, timeout=None: "
                "event_wait(self, timeout / 600 if timeout is not None else None)\n"
                + lock_program(script))
        return [sys.executable, "-u", "-c", body, *lock_argv(script, path, seconds)]

    def test_shared_lock_wait_reports_activity_until_acquired(self):
        for script in (SMOKE, E2E):
            with self.subTest(script=script.name):
                path = self.root / "private.lock"
                with path.open("a") as holder:
                    fcntl.flock(holder, fcntl.LOCK_EX)
                    release = threading.Timer(1.5, fcntl.flock, args=(holder, fcntl.LOCK_UN))
                    release.start()
                    try:
                        cmd = shlex.join(self.fast_lock(script, path, 5))
                        started = time.monotonic()
                        with patch.object(worker, "ACTIVITY_POLL", 0.05):
                            ok, text = run.run_done_when(
                                [cmd], self.root, self.root / "lock.log", set(), silence=0.5)
                    finally:
                        release.cancel()
                        release.join()
                self.assertTrue(ok, text)
                self.assertGreater(time.monotonic() - started, 0.5)
                output = text.split("[exit 0]\n", 1)[1].splitlines()
                self.assertGreaterEqual(output.count("waiting"), 3)
                self.assertEqual(output[-1], "held")

    def test_shared_lock_wait_stays_bounded_and_stops_reporting(self):
        for script in (SMOKE, E2E):
            with self.subTest(script=script.name):
                path = self.root / "private.lock"
                with path.open("a") as holder:
                    fcntl.flock(holder, fcntl.LOCK_EX)
                    result = subprocess.run(self.fast_lock(script, path, 0.5),
                                            capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 75, result.stderr)
                output = result.stdout.splitlines()
                self.assertGreaterEqual(output.count("waiting"), 3)
                self.assertEqual(output[-1], "busy")
                self.assertFalse(result.stderr)

    def recovering(self, stack, kind, stalls):
        directory = self.root / "runs" / "recovering"
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": directory.name, "state": "running", "pid": 999999999,
                 "round_summaries": [], "stalls": stalls, "silence_minutes": 17}
        run.save_state(directory, state)
        args = ["bash", "-c", "sleep 600"]
        child = 999999998 if kind != "none" else None
        stack.enter_context(patch.object(run, "run_dirs", return_value=[directory]))
        stack.enter_context(patch.object(run, "process_active", return_value=True))
        stack.enter_context(patch.object(run, "handover_executor", return_value=None))
        stack.enter_context(patch.object(watch, "step_for_run",
                                         return_value=(kind, kind, child, args)))
        stack.enter_context(patch.object(watch, "loop_children",
                                         return_value=[(child, args)] if child else []))
        written = stack.enter_context(patch.object(watch, "run_last_write", return_value=1000))
        kill = stack.enter_context(patch.object(watch, "kill_tree"))
        resume = stack.enter_context(patch.object(watch, "launch_resume"))
        return directory, written, kill, resume

    def test_tick_leaves_cleanup_time_without_spending_a_stall_rung(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        for kind in ("done-when", "worker", "reviewer", "none"):
            for stalls in ([], [{"action": "killed step", "time": 900}]):
                with self.subTest(kind=kind, stalls=stalls), ExitStack() as stack:
                    directory, written, kill, resume = self.recovering(stack, kind, stalls)
                    due = 1000 + 17 * 60
                    for offset in (0, worker.KILL_GRACE, grace - 0.01):
                        watch.recover_runs({}, log=lambda _: None, now=due + offset)
                    kill.assert_not_called()
                    resume.assert_not_called()
                    self.assertEqual(run.read_state(directory)["stalls"], stalls)
                    # The loop writes its diagnostic before the next tick; no recovery
                    # was charged to this normal watchdog stop, even on rung two.
                    written.return_value = due + worker.KILL_GRACE
                    watch.recover_runs({}, log=lambda _: None, now=due + grace + 0.01)
                    kill.assert_not_called()
                    resume.assert_not_called()

    def test_tick_recovers_a_still_silent_loop_after_cleanup_time(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        for kind in ("done-when", "worker", "reviewer", "none"):
            with self.subTest(kind=kind), ExitStack() as stack:
                directory, _, kill, resume = self.recovering(stack, kind, [])
                watch.recover_runs({}, log=lambda _: None, now=1000 + 17 * 60 + grace + 0.01)
                kill.assert_called_once()
                self.assertEqual(len(run.read_state(directory)["stalls"]), 1)
                self.assertIn("no output for 17 min", (directory / "log.txt").read_text())
                self.assertEqual(resume.call_count, 1 if kind == "none" else 0)

    def waiting(self, directory, until, pid=999999999):
        state = run.read_state(directory)
        state["transient_wait"] = {"until": until, "pid": pid}
        run.save_state(directory, state)

    def test_tick_leaves_a_loop_in_its_own_transient_wait_alone(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        for kind in ("worker", "none"):
            for stalls in ([], [{"action": "killed step", "time": 900}],
                           [{"action": "killed step", "time": 900}, {"action": "resumed",
                                                                     "time": 950}]):
                with self.subTest(kind=kind, stalls=len(stalls)), ExitStack() as stack:
                    directory, _, kill, resume = self.recovering(stack, kind, stalls)
                    # an hourly wait began with the last write: its hour is not a silence
                    self.waiting(directory, 1000 + 3600)
                    for now in (1000 + 17 * 60 + grace + 0.01, 1000 + 3599,
                                1000 + 3600 + 17 * 60 + grace - 0.01):
                        watch.recover_runs({}, log=lambda _: None, now=now)
                    kill.assert_not_called()
                    resume.assert_not_called()
                    state = run.read_state(directory)
                    self.assertEqual((state["state"], state["stalls"]), ("running", stalls))
                    # past the wait, the silence is the loop's own again
                    watch.recover_runs({}, log=lambda _: None,
                                       now=1000 + 3600 + 17 * 60 + grace + 0.01)
                    self.assertEqual(len(run.read_state(directory)["stalls"]), len(stalls) + 1)

    def test_a_dead_loops_wait_does_not_hold_the_clock_for_its_resume(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        with ExitStack() as stack:
            directory, _, kill, _ = self.recovering(stack, "worker", [])
            self.waiting(directory, 1000 + 3600, pid=999999997)
            watch.recover_runs({}, log=lambda _: None, now=1000 + 17 * 60 + grace + 0.01)
            kill.assert_called_once()
            self.assertEqual(len(run.read_state(directory)["stalls"]), 1)

    def test_foreground_tool_output_without_harness_events_is_retried(self):
        cfg = self.adapter(
            "import subprocess\n"
            "n = int((out.parent / 'n').read_text()) if (out.parent / 'n').exists() else 0\n"
            "(out.parent / 'n').write_text(str(n + 1))\n"
            "(out / 'events.jsonl').write_text('{\"type\":\"tool_use\"}\\n')\n"
            "if n == 0:\n"
            " with (out / 'tool-output.log').open('w') as output:\n"
            "  child = subprocess.Popen([sys.executable, '-u', '-c', "
            "\"import time\\nwhile True:\\n print('working', flush=True); time.sleep(.05)\"], "
            "stdout=output)\n"
            "  (out / 'child.pid').write_text(str(child.pid))\n"
            "  child.wait()\n"
            "else:\n"
            " (out / 'final.md').write_text('## Summary\\nFinished')\n")
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                cfg["models"]["fixture"]["harness"] = harness
                out = self.root / harness / "executor"
                with patch.object(worker.time, "monotonic", side_effect=Clock(600)), \
                        patch.object(run, "TRANSIENT_BACKOFF", (0, 0, 0, 0, 0)):
                    code, text, _, dead = run.call_retrying(
                        cfg, "fixture", "do it", self.root, out, "executor", None, lambda _: None)
                self.assertEqual((code, dead), (0, False))
                self.assertIn("Finished", text)
                self.assertGreater((out / "tool-output.log").stat().st_size, 0)
                self.assertTrue(watch._gone(int((out / "child.pid").read_text())))

    def test_status_why_prints_recorded_limits(self):
        directory = self.root / "runs" / "fixture"
        directory.mkdir(parents=True)
        state = {"run_id": "fixture", "title": "Fixture", "state": "pass", "verdict": "PASS",
                 "rounds": 3, "round_summaries": [], "reported": True,
                 "silence_minutes": 17, "ceiling_hours": 5}
        run.save_state(directory, state)
        for extra in ([], ["--plain"]):
            with self.subTest(extra=extra):
                out = io.StringIO()
                with patch.object(config, "RUNS", directory.parent), redirect_stdout(out):
                    self.assertEqual(run.cmd_status(["fixture", "--why", *extra]), 0)
                self.assertIn("silence_minutes=17, ceiling_hours=5", out.getvalue())


if __name__ == "__main__":
    unittest.main()

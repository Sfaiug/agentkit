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
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, gitcall, host, run, staffing, status, turns, watch, worker
from agentkit import record
from agentkit import task as taskfile


class Clock:
    """Advance only on the watchdog's ticks, leaving real child processes to run.

    Time stands still until `ready()`, whatever the test's command must have done by its stop:
    a busy host may need seconds to start a command's box, exec its child or print.
    """

    def __init__(self, step, ready=lambda: True):
        self.owner = threading.current_thread()
        self.step, self.now, self.ready = step, 0, ready
        self.seen = set()

    def __call__(self):
        current = threading.current_thread()
        if current is not self.owner:
            if current in self.seen and self.ready():
                self.now += self.step
            self.seen.add(current)
        return self.now


class Output:
    """Advance ten minutes each time `path` is found grown: only output spends time, however
    slowly a busy host prints or polls. Silence is twenty: output the watchdog misses, landing
    between this look and its own, is a step behind, never two. Past `until`, `past` is made,
    for a command printing until then."""

    def __init__(self, path, until=float("inf")):
        self.path, self.until, self.past = path, until, path.with_name("past")
        self.now, self.size = 0, 0

    def __call__(self):
        size = self.path.stat().st_size if self.path.exists() else 0
        if size != self.size:
            self.now, self.size = self.now + 600, size
        if self.now > self.until:
            self.past.touch()
        return self.now


class Silence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-silence-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(patch.stopall)
        self.enterContext(account_home(self.root))
        # ak's state is the sandbox's: a run parked below tells its seat, and run from a seat
        # that was the real seat, held with a stray "needs you" that blocked its hand-backs
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            patch.object(config, key, self.root / key.lower()).start()
        # a worker running this file carries its own run's marker, and a silent turn below
        # ends every process marked with the run it inherits
        patch.dict(os.environ, {"HOME": str(self.root), "AGENTKIT_RUN": "",
                                "AGENTKIT_SESSION": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
                                "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
                                "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}).start()
        patch.object(gitcall, "dirty_paths", return_value=[]).start()
        patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}).start()

    def command(self, text):
        return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(text)}"

    def printed(self, line):
        return lambda: line in (self.root / "donewhen.log").read_bytes()

    def running(self, *argv):
        """Whether a process under this one runs `argv` yet."""
        def check():
            table = watch._proc_table()
            return any(table.get(pid, (0, "", []))[2] == [*argv]
                       for child, _ in watch.loop_children(os.getpid())
                       for pid in watch.descendants(child))
        return check

    def silent(self, out, written):
        """Whether the first attempt at the turn in `out` has written to `written`, unretried:
        time is the silent attempt's alone, so no host is too slow for a retry to answer."""
        return lambda: (out / written).is_file() and (out / written).stat().st_size > 0 \
            and not out.with_name(f"{out.name}-retry1").exists()

    def gate(self, commands, clock):
        logs = []
        with patch.object(worker.time, "monotonic", side_effect=clock):
            ok, text = gate.run_done_when(commands, self.root, self.root / "donewhen.log",
                                         set(), log=logs.append)
        self.assertEqual(logs.pop(0), "suite runs here: command is not sent to the suite helper "
                                     "(does not name AK_SHARD)")
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
        meta, body, title = taskfile.parse_task(path)
        self.assertEqual(meta, {})
        self.assertEqual(title, "Title")
        self.assertIn("## Goal", body)
        self.assertIn("## Constraints", body)
        every, once = taskfile.done_when_groups(body, path)
        self.assertTrue(every)
        self.assertEqual(once, ["bash tests/smoke.sh"])

    def test_old_keys_are_ignored_with_one_log_line_each(self):
        task = self.root / "task.md"
        keys = ("done_when_minutes", "turn_hours", "stall_minutes")
        task.write_text("---\n" + "".join(f"{key}: never\n" for key in keys)
                        + "---\n# Compatibility\n")
        meta, _, _ = taskfile.parse_task(task)
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
        clock = Clock(60 * record.SILENCE_MINUTES / 2)
        ok, text, logs = self.gate([cmd], clock)
        self.assertFalse(ok)
        self.assertGreaterEqual(clock.now, 60 * record.SILENCE_MINUTES)
        self.assertIn("[killed at the limit]", text)
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].startswith(f"done-when: stopped after 20 min of silence: {cmd} "
                                           "(last output: (no output)); still running: "))

    def test_silent_command_keeps_its_last_output_line(self):
        cmd = self.command("import time; print('first'); print('last'); time.sleep(600)")
        ok, text, logs = self.gate([cmd], Clock(600, self.printed(b"\nlast\n")))
        self.assertFalse(ok)
        self.assertIn("first\nlast", text)
        self.assertIn(f"{cmd} (last output: last)", logs[0])

    def test_silence_stop_names_the_sleeping_child(self):
        path = self.root / "donewhen.log"
        ok, text, logs = self.gate(["sleep 600 & wait"], Clock(600, self.running("sleep", "600")))
        self.assertFalse(ok, text)
        self.assertEqual(len(logs), 1)
        detail = logs[0].split("(last output: (no output))", 1)[1]
        self.assertRegex(detail, r"^; still running: sleep 600 \(\d+s\)$")
        self.assertIn(logs[0], text)
        self.assertEqual(path.read_text(), text)

    def test_running_commands_keeps_each_live_leaf_and_its_age(self):
        long = "check " + "x" * 160
        table = {
            100: (90, "S", ["bash", "-c", "checks"]),
            101: (100, "S", ["bash", "checks.sh"]),
            102: (101, "S", ["python3", "tests/check.py"]),
            103: (100, "S", [long]),
            104: (103, "Z", ["finished"]),
            105: (1, "S", ["sleep", "600"]),
            106: (101, "S", ["detached", "check"]),
            107: (90, "S", ["unrelated"]),
            108: (100, "X", ["dead"]),
        }
        with patch.object(watch, "_proc_table", return_value=table), \
                patch.object(os, "getpgid", side_effect=lambda pid: pid if pid >= 106 else 100), \
                patch.object(host, "process_identity", side_effect=lambda pid: {"started_at": pid}), \
                patch.object(gate.time, "time", return_value=131):
            self.assertEqual(gate._running_commands(100), [
                "python3 tests/check.py (29s)", f"{long[:159]}… (28s)",
                "sleep 600 (26s)", "detached check (25s)"])

    def test_background_child_holding_output_does_not_escape_silence(self):
        child = self.root / "child.lock"
        cmd = f"flock -x {shlex.quote(str(child))} sleep 600 &"
        ok, text, logs = self.gate([cmd], Clock(600, self.running("sleep", "600")))
        self.assertFalse(ok, text)
        self.assertIn("20 min of silence", logs[0])
        self.assertRegex(logs[0], r"; still running: sleep 600 \(\d+s\)$")
        with child.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_chatty_command_past_silence_total_is_not_killed(self):
        # No newline: any output counts, and it reaches the gate log before exit.
        clock = Output(self.root / "donewhen.log", until=60 * record.SILENCE_MINUTES)
        cmd = self.command(f"import os, time\nwhile not os.path.exists({str(clock.past)!r}):\n"
                           " print('.', end='', flush=True)\n time.sleep(.1)")
        ok, text, logs = self.gate([cmd], clock)
        self.assertTrue(ok, text)
        self.assertGreater(clock.now, 60 * record.SILENCE_MINUTES)
        self.assertIn("[exit 0]", text)
        self.assertEqual(logs, [])

    def test_ceiling_kills_a_command_that_prints_forever(self):
        cmd = self.command("import time\nwhile True:\n print('still going', flush=True)\n time.sleep(.05)")
        clock = Output(self.root / "donewhen.log")
        # thirty-six steps of output reach the ceiling, each a poll apart at least
        with patch.object(worker, "ACTIVITY_POLL", .05):
            ok, text, logs = self.gate([cmd, "echo never"], clock)
        self.assertFalse(ok)
        self.assertGreaterEqual(clock.now, 3600 * record.CEILING_HOURS)
        self.assertIn("6h ceiling", logs[0])
        self.assertIn("last output: still going", logs[0])
        self.assertIn("; still running: ", logs[0])
        self.assertNotIn("$ echo never", text)

    def starting(self, clock, began):
        """Why a silent command stopped, the watchdog told `began` says of its box, and when."""
        reasons = []
        with patch.object(worker.time, "monotonic", side_effect=clock), \
                patch.object(worker, "ACTIVITY_POLL", .01):
            worker.limited(["sleep", "600"], 100 * worker.BOX_START, silence=90,
                           activity=self.root / "silent.log", began=began,
                           on_timeout=lambda why, _pid: reasons.append(why),
                           stdout=subprocess.DEVNULL)
        return reasons

    def test_silence_counts_from_the_box_being_up(self):
        clock, asked = Clock(30), []

        def began():
            asked.append(clock.now)
            return len(asked) == 4

        self.assertEqual(self.starting(clock, began), ["silence"])
        self.assertEqual(len(asked), 4)
        self.assertGreaterEqual(clock.now - asked[-1], 90)

    def test_a_box_that_never_comes_up_still_goes_silent(self):
        clock = Clock(30)
        self.assertEqual(self.starting(clock, lambda: False), ["silence"])
        self.assertGreaterEqual(clock.now, worker.BOX_START + 90)

    def test_a_box_whose_start_cannot_be_read_still_goes_silent(self):
        self.assertEqual(self.starting(Clock(30), Mock(side_effect=PermissionError)), ["silence"])

    def test_a_declared_bound_holds_until_its_very_end(self):
        proc = subprocess.Popen(["timeout", "100", "sh", "-c", "echo; exec sleep 100"],
                                stdout=subprocess.PIPE)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)     # which `timeout` passes on to its `sleep`
        self.addCleanup(proc.stdout.close)
        # Popen returns as the child starts its exec, its /proc argv maybe still this process's;
        # once `timeout` runs its command, its argv is its own
        proc.stdout.readline()
        for age, held in ((99.9, True), (100, False)):
            with self.subTest(age=age), patch.object(host, "process_age", return_value=age):
                self.assertEqual(worker.within_declared_timeout(proc.pid), held)

    def test_silent_turn_is_retried_as_transport_death(self):
        cfg = self.adapter(
            "(out / 'events.jsonl').write_text('{\"type\":\"thread.started\",\"thread_id\":\"sid\"}\\n')\n"
            "if len(sys.argv) == 7:\n time.sleep(600)\n"
            "(out / 'final.md').write_text('## Summary\\nFinished')\n")
        logs = []
        # two levels under the sandbox, as a round's out dir sits under its run: the turn reads
        # the run directory as the out dir's grandparent, and one level up here is the checkout
        out = self.root / "turns" / "executor"
        with patch.object(worker.time, "monotonic",
                          side_effect=Clock(600, self.silent(out, "events.jsonl"))), \
                patch.object(turns, "TRANSIENT_BACKOFF", (0, 0)):
            code, text, sid, dead = turns.call_retrying(
                cfg, "fixture", "do it", self.root, out, "executor", None, logs.append)
        self.assertEqual((code, sid, dead), (0, "sid", False))
        self.assertIn("Finished", text)
        self.assertTrue(any("emitted no event for 20m" in line and "resuming session sid" in line
                            for line in logs), logs)
        self.assertEqual(sum("retrying in 0s" in line for line in logs), 1)
        self.assertTrue((self.root / "turns" / "executor-retry1" / "final.md").exists())
        self.assertFalse((self.root / "turns" / "executor" / "final.md").exists())

    def test_chatty_turn_has_no_total_cap(self):
        cfg = self.adapter(
            "time.sleep(2.2)\n"
            "for _ in range(300):\n"
            " if (out / 'past').exists(): break\n"
            " with (out / 'events.jsonl').open('a') as fh: fh.write('{\"type\":\"event\"}\\n')\n"
            " time.sleep(.1)\n"
            "(out / 'final.md').write_text('## Summary\\nFinished')\n")
        out = self.root / "turns" / "executor"
        clock = Output(out / "events.jsonl", until=3600 * record.CEILING_HOURS)
        with patch.object(worker.time, "monotonic", side_effect=clock), \
                patch.object(worker, "ACTIVITY_POLL", .05), \
                patch.object(turns, "transient_wait", side_effect=AssertionError(
                    "the chatty turn must finish without retries")):
            code, text, _, dead = turns.call_retrying(
                cfg, "fixture", "do it", self.root, out,
                "executor", None, lambda _: None)
        self.assertEqual((code, dead), (0, False))
        self.assertIn("Finished", text)
        self.assertGreater(clock.now, 3600 * record.CEILING_HOURS)

    def test_run_json_records_new_fields_and_removes_old_fields(self):
        state = {"done_when_minutes": 45, "turn_hours": 3, "stall_minutes": 60}
        record.save_state(self.root, state)
        self.assertEqual(json.loads((self.root / "run.json").read_text()),
                         {"silence_minutes": 20, "ceiling_hours": 6})

    def test_resumed_run_keeps_recorded_limits(self):
        state = {"silence_minutes": 17, "ceiling_hours": 5,
                 "base": None, "rounds": 3, "executor": None, "reviewer": None,
                 "round_summaries": [], "scratch": True}
        record.save_state(self.root, state)
        with patch.object(record, "SILENCE_MINUTES", 21), patch.object(record, "CEILING_HOURS", 7):
            saved = record.read_state(self.root)
            record.save_state(self.root, saved)
            lp = run.Loop({}, self.root, saved, {}, lambda _: None, self.root, "", [], "")
            self.assertEqual((lp.turn_limit, lp.done_when_limit), (17 * 60, 5 * 3600))
            self.assertEqual(turns.stall_minutes_for(self.root, saved), 17)
            self.assertAlmostEqual(watch.stall_allowance(saved, "done-when", 17),
                                   17 + (worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL) / 60)
        self.assertEqual((saved["silence_minutes"], saved["ceiling_hours"]), (17, 5))

    def recovering(self, stack, kind, stalls):
        directory = self.root / "runs" / "recovering"
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": directory.name, "state": "running", "pid": 999999999,
                 "round_summaries": [], "stalls": stalls, "silence_minutes": 17}
        record.save_state(directory, state)
        args = ["bash", "-c", "sleep 600"]
        child = 999999998 if kind != "none" else None
        stack.enter_context(patch.object(record, "run_dirs", return_value=[directory]))
        stack.enter_context(patch.object(record, "process_active", return_value=True))
        stack.enter_context(patch.object(staffing, "handover_executor", return_value=None))
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
                    self.assertEqual(record.read_state(directory)["stalls"], stalls)
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
                self.assertEqual(len(record.read_state(directory)["stalls"]), 1)
                self.assertIn("no output for 17 min", (directory / "log.txt").read_text())
                self.assertEqual(resume.call_count, 1 if kind == "none" else 0)

    def waiting(self, directory, until, pid=999999999):
        state = record.read_state(directory)
        state["transient_wait"] = {"until": until, "pid": pid}
        record.save_state(directory, state)

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
                    state = record.read_state(directory)
                    self.assertEqual((state["state"], state["stalls"]), ("running", stalls))
                    # past the wait, the silence is the loop's own again
                    watch.recover_runs({}, log=lambda _: None,
                                       now=1000 + 3600 + 17 * 60 + grace + 0.01)
                    self.assertEqual(len(record.read_state(directory)["stalls"]), len(stalls) + 1)

    def test_a_dead_loops_wait_does_not_hold_the_clock_for_its_resume(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        with ExitStack() as stack:
            directory, _, kill, _ = self.recovering(stack, "worker", [])
            self.waiting(directory, 1000 + 3600, pid=999999997)
            watch.recover_runs({}, log=lambda _: None, now=1000 + 17 * 60 + grace + 0.01)
            kill.assert_called_once()
            self.assertEqual(len(record.read_state(directory)["stalls"]), 1)

    def test_foreground_tool_output_without_harness_events_is_retried(self):
        cfg = self.adapter(
            "import subprocess\n"
            "n = int((out.parent / 'n').read_text()) if (out.parent / 'n').exists() else 0\n"
            "(out.parent / 'n').write_text(str(n + 1))\n"
            "(out / 'events.jsonl').write_text('{\"type\":\"tool_use\"}\\n')\n"
            "if n == 0:\n"
            " with (out / 'tool-output.log').open('w') as output:\n"
            "  child = subprocess.Popen([sys.executable, '-u', '-c', "
            "\"import fcntl, sys, time\\n"
            "lock = open(sys.argv[1], 'w')\\n"
            "fcntl.flock(lock, fcntl.LOCK_EX)\\n"
            "while True:\\n print('working', flush=True); time.sleep(.05)\", "
            "str(out / 'child.lock')], "
            "stdout=output)\n"
            "  child.wait()\n"
            "else:\n"
            " (out / 'final.md').write_text('## Summary\\nFinished')\n")
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                cfg["models"]["fixture"]["harness"] = harness
                out = self.root / harness / "executor"
                with patch.object(worker.time, "monotonic",
                                  side_effect=Clock(600, self.silent(out, "tool-output.log"))), \
                        patch.object(turns, "TRANSIENT_BACKOFF", (0, 0, 0, 0, 0)):
                    code, text, _, dead = turns.call_retrying(
                        cfg, "fixture", "do it", self.root, out, "executor", None, lambda _: None)
                self.assertEqual((code, dead), (0, False))
                self.assertIn("Finished", text)
                self.assertGreater((out / "tool-output.log").stat().st_size, 0)
                # The child's lock proves its death across PID namespaces.
                with (out / "child.lock").open() as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_status_why_prints_recorded_limits(self):
        directory = self.root / "runs" / "fixture"
        directory.mkdir(parents=True)
        state = {"run_id": "fixture", "title": "Fixture", "state": "pass", "verdict": "PASS",
                 "rounds": 3, "round_summaries": [], "reported": True,
                 "silence_minutes": 17, "ceiling_hours": 5}
        record.save_state(directory, state)
        for extra in ([], ["--plain"]):
            with self.subTest(extra=extra):
                out = io.StringIO()
                with patch.object(config, "RUNS", directory.parent), redirect_stdout(out):
                    self.assertEqual(status.cmd_status(["fixture", "--why", *extra]), 0)
                self.assertIn("silence_minutes=17, ceiling_hours=5", out.getvalue())


if __name__ == "__main__":
    unittest.main()

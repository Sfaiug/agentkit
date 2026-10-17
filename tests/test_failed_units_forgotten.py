"""Daily retention forgets only old ak failures whose run no longer needs the evidence.

Offline: the user manager, its clock and every systemctl command are fixtures.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gc, handback, orch, record

DAY = 86400


class FailedUnitsForgotten(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 10 * DAY
        self.units, self.commands, self.failures = {}, [], {}
        self.stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=True))
        self.stack.enter_context(patch.object(gc.time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(gc.time, "monotonic", side_effect=lambda: self.now))
        # Exercise the real retention lock and daily stamp, without unrelated file cleanup.
        self.stack.enter_context(patch.object(gc, "gc_candidates", return_value=()))
        self.stack.enter_context(patch.object(gc.subprocess, "run", side_effect=self.systemctl))

    def unit(self, name, age=2 * DAY, **fields):
        self.units[name] = {"ActiveState": "failed", "Result": "oom-kill",
                            "OOMPolicy": "stop", "LoadState": "loaded",
                            "StateChangeTimestampMonotonic": str((self.now - age) * 1_000_000),
                            **fields}
        return name

    def receipt(self, name, scope, state="running", **fields):
        directory = config.RUNS / name
        directory.mkdir(exist_ok=True)
        state = {"run_id": name, "state": state, "scope": scope, **fields}
        (directory / "run.json").write_text(json.dumps(state))
        return state

    def systemctl(self, command, **_kw):
        self.assertEqual(command[:2], ["systemctl", "--user"])
        self.commands.append(command)
        action, *args = command[2:]
        failure = self.failures.get((action, args[0]))
        if isinstance(failure, Exception):
            raise failure
        if failure:
            return subprocess.CompletedProcess(command, failure, stdout="", stderr="unavailable")
        if action == "list-units" and "--failed" not in args:
            output = ""         # the test-unit sweep's listing: no unit is active
        elif action == "list-units":
            self.assertIn("--plain", args)
            output = "\n".join(f"{name} loaded failed failed fixture" for name in self.units)
        elif action == "show":
            output = "\n".join(f"{key}={value}" for key, value in self.units[args[0]].items())
        else:
            self.assertEqual(action, "reset-failed")
            self.assertEqual(len(args), 1)  # never reset every unit or pass a wildcard
            self.units.pop(args[0])
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def collect(self):
        gc.gc(lambda _: None, automatic=True)

    def resets(self):
        return [command[3] for command in self.commands if command[2] == "reset-failed"]

    def test_only_old_unheld_ak_failures_are_reset(self):
        old = [self.unit(f"agentkit-{kind}-acme.scope")
               for kind in ("run", "seat", "lander", "job", "older-version")]
        old.append(self.unit("agentkit-run-ended.service", age=DAY))
        self.receipt("ended", "agentkit-run-ended", state="fail")
        recent = self.unit("agentkit-run-recent.scope", age=3600)
        foreign = self.unit("acme.service")
        self.collect()
        self.assertCountEqual(self.resets(), old)
        self.assertEqual(set(self.units), {recent, foreign})
        self.assertFalse(any(foreign in command for command in self.commands))

    def test_unconcluded_runs_hold_both_possible_unit_suffixes(self):
        for state in (*record.GOING, "interrupted", "unknown"):
            scope = f"agentkit-run-{state}"
            self.receipt(state, scope, state=state)
            self.unit(scope + ".scope")
            self.unit(scope + ".service")
        for suffix in ("scope", "service"):
            scope = self.unit(f"agentkit-run-qualified.{suffix}")
            self.receipt(suffix, scope)
        self.collect()
        self.assertEqual(self.resets(), [])

    def test_oom_evidence_stays_until_the_run_concludes(self):
        unit = self.unit("agentkit-run-capped.scope")
        state = self.receipt("capped", unit, memory_cap_mb=1024)
        self.collect()
        self.assertEqual(self.resets(), [])
        self.assertEqual(handback.memory_cap_reason(state), "killed: memory cap 1 GB")
        self.receipt("capped", unit, state="fail")
        self.now += DAY
        self.collect()
        self.assertEqual(self.resets(), [unit])

    def test_unknown_age_and_no_longer_failed_units_stay(self):
        for index, stamp in enumerate(("", "invalid", "0", "-1", str((self.now + DAY) * 1_000_000))):
            self.unit(f"agentkit-run-age{index}.scope", StateChangeTimestampMonotonic=stamp)
        self.unit("agentkit-run-restarted.scope", ActiveState="active")
        self.unit("agentkit-run-no-stamp.scope")
        del self.units["agentkit-run-no-stamp.scope"]["StateChangeTimestampMonotonic"]
        self.collect()
        self.assertEqual(self.resets(), [])

    def test_automatic_collection_is_at_most_daily(self):
        first = self.unit("agentkit-run-first.scope")
        self.collect()
        asked = len(self.commands)
        second = self.unit("agentkit-run-second.scope")
        self.collect()
        self.assertEqual(len(self.commands), asked)
        self.now += DAY
        self.collect()
        self.assertEqual(self.resets(), [first, second])

    def test_unreadable_run_record_defers_reset(self):
        self.unit("agentkit-run-unreadable.scope")
        self.receipt("unreadable", "agentkit-run-unreadable")
        (config.RUNS / "unreadable" / "run.json").write_text("{")
        self.collect()
        self.assertEqual(self.resets(), [])

    def test_unlistable_runs_defer_reset(self):
        self.unit("agentkit-run-unlisted.scope")
        with patch.object(gc.os, "listdir", side_effect=PermissionError):
            self.collect()
        self.assertEqual(self.resets(), [])

    def test_manager_unavailable_is_harmless(self):
        with patch.object(orch, "user_manager", return_value=False):
            self.collect()
        self.assertEqual(self.commands, [])
        for failure in (1, FileNotFoundError(), subprocess.TimeoutExpired("systemctl", 5)):
            with self.subTest(failure=failure):
                self.now += DAY
                self.failures[("list-units", "--failed")] = failure
                self.collect()
        self.assertEqual(self.resets(), [])

    def test_one_unreadable_or_unresettable_unit_does_not_stop_the_sweep(self):
        for index, failure in enumerate((1, OSError(), subprocess.TimeoutExpired("systemctl", 5))):
            unit = self.unit(f"agentkit-run-unreadable{index}.scope")
            self.failures[("show", unit)] = failure
        unit = self.unit("agentkit-run-reset-refused.scope")
        self.failures[("reset-failed", unit)] = 1
        reset = self.unit("agentkit-run-reset.scope")
        self.collect()
        self.assertEqual(self.resets(), [unit, reset])
        self.assertIn(unit, self.units)
        self.assertNotIn(reset, self.units)


if __name__ == "__main__":
    unittest.main(verbosity=2)

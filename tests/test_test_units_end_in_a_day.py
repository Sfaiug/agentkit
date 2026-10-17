"""Daily retention stops a unit a test suite left in its slice once it is a day old.

Offline: the user manager, its clock and every systemctl command are fixtures.
"""

import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import gc, orch

DAY = 86400


class TestUnitsEndInADay(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 30 * DAY
        self.units, self.commands = {}, []
        self.stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=True))
        self.stack.enter_context(patch.object(gc.time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(gc.time, "monotonic", side_effect=lambda: self.now))
        # Exercise the real retention lock and daily stamp, without unrelated file cleanup.
        self.stack.enter_context(patch.object(gc, "gc_candidates", return_value=()))
        self.stack.enter_context(patch.object(gc.subprocess, "run", side_effect=self.systemctl))

    def unit(self, name, slice_, age):
        self.units[name] = {"Id": name, "Slice": slice_,
                            "ActiveEnterTimestampMonotonic": str((self.now - age) * 1_000_000)}
        return name

    def systemctl(self, command, **_kw):
        self.assertEqual(command[:2], ["systemctl", "--user"])
        self.commands.append(command)
        action, *args = command[2:]
        output = ""
        if action == "list-units" and "--failed" not in args:
            self.assertIn("--state=active", args)
            self.assertIn("--type=service,scope", args)   # never a slice a neighbour shares
            output = "\n".join(f"{name} loaded active running fixture" for name in self.units)
        elif action == "show":
            output = "\n\n".join("\n".join(f"{key}={value}" for key, value in self.units[name].items())
                                 for name in args if name in self.units)
        elif action == "stop":
            self.assertEqual(args[0], "--no-block")
            self.assertEqual(len(args), 2)
            self.units.pop(args[1])
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def stops(self):
        return [command[-1] for command in self.commands if command[2] == "stop"]

    def test_only_day_old_test_slice_units_are_stopped(self):
        left = self.unit("agentkit-seat-new.service", "agentkit-test.slice", DAY + 60)
        run = self.unit("agentkit-run-acme.scope", "agentkit-test-runs.slice", 2 * DAY)
        fresh = self.unit("tmux-spawn-acme.scope", "agentkit-test.slice", 3600)
        seat = self.unit("agentkit-seat-fix-api.service", "agentkit-seats.slice", 7 * DAY)
        gc.gc(lambda _: None, automatic=True)
        self.assertCountEqual(self.stops(), [left, run])
        self.assertEqual(set(self.units), {fresh, seat})

    def test_manager_unavailable_asks_nothing(self):
        self.unit("agentkit-seat-new.service", "agentkit-test.slice", 2 * DAY)
        with patch.object(orch, "user_manager", return_value=False):
            gc.gc(lambda _: None, automatic=True)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

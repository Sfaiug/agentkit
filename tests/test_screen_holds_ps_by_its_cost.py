"""A screen's pass holds the process table while reading it costs little; the rest as before."""

import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import look, open_runs, orch


class HeldByItsCost(Sandbox):
    def test_a_pass_holds_a_costly_reading_longer(self):
        clock = [1000.0]
        def ps(*_a, **_kw):
            clock[0] += 0.2                 # what a reading took
            return subprocess.CompletedProcess([], 0, stdout="7 1 claude\n")
        orch._PROCESSES.clear()
        self.addCleanup(orch._PROCESSES.clear)
        with patch.object(orch.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(orch.subprocess, "run", side_effect=ps) as run:
            def asks(after):
                clock[0] += after
                orch.processes()
                return run.call_count
            self.assertEqual([asks(0), asks(orch.AGENT_LOOK_EVERY)], [1, 2])   # outside a pass
            with look.one_look():
                held = min(open_runs.CEILING, 0.2 / open_runs.SHARE)
                self.assertEqual([asks(held - 1), asks(2)], [2, 3])


if __name__ == "__main__":
    unittest.main()

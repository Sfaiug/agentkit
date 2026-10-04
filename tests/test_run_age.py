"""A run's age keeps counting while it waits in its repository's line; a finished run's stops."""

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AGENTKIT_HOME", "/nonexistent-agentkit-home")

from agentkit import menu, terminal  # noqa: E402

HOURS = 3600


class RunAge(unittest.TestCase):
    def test_a_run_in_the_line_reads_its_whole_age(self):
        state = {"state": "waiting", "started_at": time.time() - 7 * HOURS, "finished_at": None,
                 "waiting_on": {"line": ".merge-abc.lock", "joined": time.time() - 6 * HOURS}}
        self.assertEqual(terminal.format_age(menu.run_age_secs(state)), "7h")

    def test_a_finished_run_reads_start_to_finish(self):
        now = time.time()
        state = {"state": "pass", "started_at": now - 9 * HOURS, "finished_at": now - 7 * HOURS}
        self.assertEqual(terminal.format_age(menu.run_age_secs(state)), "2h")

    def test_a_run_waiting_on_a_provider_keeps_its_recorded_end(self):
        now = time.time()
        state = {"state": "waiting", "started_at": now - 5 * HOURS, "finished_at": now - 4 * HOURS,
                 "waiting_on": {"provider": "openai"}}
        self.assertEqual(terminal.format_age(menu.run_age_secs(state)), "1h")


if __name__ == "__main__":
    unittest.main()

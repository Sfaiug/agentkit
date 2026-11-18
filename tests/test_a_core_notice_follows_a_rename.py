"""A seat renamed after the tick read its name, while the tick reads its CPU time, is asked and
owed its core notice (`cores.tell`) under its new name: one still owed it there is its only one."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, cores, watch

SCOPE = Path("agentkit-seat-fix-api-89abcdef.scope")


class ACoreNoticeFollowsARename(Sandbox):
    def test_a_seat_renamed_during_the_reading_is_owed_one_notice(self):
        config.session_path("fix-api").write_text("{}")
        watch.owe_line("fix-api", None, {"line": "still owed", "cores": True})
        state = {"seat_cores": {SCOPE.name: {"at": 180, "held": 180_000_000, "since": 0,
                                             "since_held": 0, "ticks": {}}}}
        logged = []
        with patch.object(cores, "_now", return_value=360), \
                patch.object(cores.front, "scopes", return_value={SCOPE: "fix-api"}), \
                patch.object(cores.host, "cpu_held_usec", return_value=360_000_000), \
                patch.object(cores.host, "cpu_ticks",
                             side_effect=lambda _: config.rename_session("fix-api", "parser") or {}):
            cores.tell(state, logged.append)
        self.assertEqual([owed["line"] for owed in watch.seat_read("parser")["owed_lines"]],
                         ["still owed"])
        self.assertEqual([line.split(":")[0] for line in logged], ["parser"])


if __name__ == "__main__":
    unittest.main()

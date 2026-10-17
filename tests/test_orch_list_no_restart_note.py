"""`ak orch list` tells no seat to restart; offline.

A seat's hook scripts run from the live install on each event and a changed rulebook reaches it
through its own prompt hook, so a seat older than the install misses nothing a restart would give
it. A legacy seat keeps its `legacy` note.
"""

from contextlib import redirect_stdout
import io
from itertools import takewhile
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch


class NoRestartNote(Sandbox):
    def test_old_claude_seat_has_no_restart_note_and_legacy_keeps_its_own(self):
        (config.STATE / "installed-at").write_text("1000\n")     # installed after both seats
        for name in ("fix-api", "acme-old"):
            config.save_session(self.cfg, name, "opus", ["spark"])
        found = [{"name": "fix-api", "path": "/repo", "created": 900, "attached": False},
                 {"name": "acme-old", "path": "/repo", "created": 900, "attached": False,
                  "legacy": True}]
        out = io.StringIO()
        with patch.object(orch, "sessions", return_value=found), redirect_stdout(out):
            orch.cmd_list([])
        said = out.getvalue()
        self.assertEqual(config.model(self.cfg, "opus")["harness"], "claude")
        self.assertIn("fix-api", said)
        self.assertNotIn("restart", said)
        # a seat's note ends its row, or rides its own indented line where the screen is narrow
        lines = said.splitlines()
        at = next(n for n, line in enumerate(lines) if line.startswith("acme-old"))
        group = [lines[at], *takewhile(lambda line: line.startswith(" "), lines[at + 1:])]
        self.assertTrue(any(line.endswith("legacy") for line in group), said)


if __name__ == "__main__":
    unittest.main()

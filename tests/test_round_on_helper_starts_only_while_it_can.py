"""A round's piece starts on the suite helper only while its run goes on, and a piece that cannot
start there runs its commands here (`gate.run_round`).  In-process, the helper and the launch
faked, in a temporary directory."""

import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import gate, helper
from agentkit import record as run_record

AWAY = helper.Away("acme-mac", "key", "repo", "image", 1, 2, 1024, 1, "main", "", "")


class RoundOnHelper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-round-on-helper-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.said, self.here = [], []
        self.addCleanup(patch.stopall)
        patch.object(gate, "suite_cost", return_value=(None, 1, 410)).start()
        patch.object(gate, "run_done_when", side_effect=self.run_here).start()
        patch.object(gate.suite_times, "handed", return_value="").start()
        patch.object(helper, "start", return_value=(AWAY, "")).start()
        self.finish = patch.object(helper, "finish").start()

    def run_here(self, cmds, *_a, **_kw):
        self.here.extend(cmds)
        return True, "$ true\n[exit 0]"

    def round(self):
        return gate.run_round(["true"], self.root, self.root / "donewhen.log", set(), 60,
                              self.said.append, 60, self.run_dir)

    def test_a_round_stopped_while_its_piece_prepared_starts_nothing_there(self):
        (self.run_dir / "run.json").write_text(json.dumps({"state": "stopped"}))
        with patch.object(gate.worker, "limited") as launch:
            with self.assertRaises(run_record.StopRequested):
                self.round()
        launch.assert_not_called()
        self.finish.assert_called_once_with(AWAY)
        self.assertEqual(self.here, [])

    def test_a_piece_that_cannot_start_there_runs_its_commands_here(self):
        too_long = OSError(errno.E2BIG, "Argument list too long")
        with patch.object(gate.worker, "limited", side_effect=too_long):
            ok, text = self.round()
        self.assertTrue(ok)
        self.assertEqual(self.here, ["true"])
        self.finish.assert_called_once_with(AWAY)
        self.assertIn("done-when runs here: helper acme-mac failed (exit 126)", self.said)
        self.assertTrue(text.startswith("On the suite helper acme-mac, as one piece: [exit 126]\n"
                                         "[Errno 7] Argument list too long\n\n$ true\n[exit 0]"),
                        text)


if __name__ == "__main__":
    unittest.main()

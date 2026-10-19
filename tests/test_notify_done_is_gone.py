"""`ak notify done` is gone: a seat's work is done when its plan says so (owner, 19 Oct 2026).

The command is refused and records nothing, `ak notify needs` being the only form; a done
notice an older install left reads as nothing, never as a question or owed work; and nothing a
seat is told -- its rulebook, the stop hook's reason, `ak notify --help` -- names the command.
Offline: a temporary HOME, no tmux, no webhook.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, notify, watch  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SEAT = "acme-api"


class NotifyDoneIsGone(Sandbox):
    def ak(self, *argv):
        env = {**os.environ, "HOME": str(self.root), config.SESSION_ENV: SEAT,
               notify.SINK_ENV: "dry-run", "AK_RUN_ROLE": ""}
        return subprocess.run([str(REPO / "bin/ak"), *argv], env=env, capture_output=True,
                              text=True, timeout=60)

    def decide(self, session):
        return watch.session_state(SEAT, now=10000, session=session, number=3, records=[],
                                   live={"state": "at_prompt", "began": 9000}, harness=None,
                                   auth_out={}, gh_out={}, token_out=None, previous={})["word"]

    def test_the_command_is_refused_names_needs_and_records_nothing(self):
        before = sorted(self.root.rglob("*"))
        refused = self.ak("notify", "done", "Shipped the acme parser")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('ak notify needs "QUESTION"', refused.stderr)
        self.assertNotIn("notify done", refused.stderr)
        self.assertEqual(sorted(self.root.rglob("*")), before)

    def test_a_done_an_old_install_left_reads_as_nothing(self):
        config.notify_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "kind": "done", "text": "Shipped the acme parser", "time": 9000}) + "\n")
        self.assertIsNone(notify.last(SEAT))
        self.assertIsNone(notify.last(SEAT, include_seen=True))
        for session in ({"name": SEAT}, {"name": SEAT, "exited": True}):
            with self.subTest(session=session):
                self.assertNotEqual(self.decide(session), "needs you")

    def test_nothing_a_seat_is_told_names_the_command(self):
        helped = self.ak("notify", "--help")
        self.assertEqual(helped.returncode, 0)
        for told in ((REPO / "orchestrator.md").read_text(),
                     (REPO / "hooks/orchestrator-stop.sh").read_text(), helped.stdout):
            self.assertNotIn("notify done", told)


if __name__ == "__main__":
    unittest.main()

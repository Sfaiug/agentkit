"""`x` stops the popup's own seat behind it: the popup goes before the stop ends, a refusal then
left for the next menu.

Each test runs the real menu loop on a pty of its own through tests/test_close_and_info.py's
`Menu`, the stop a process of its own that waits while the test holds it; nothing here stops a
real seat, and the only processes signalled are the test's own children.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, menu as ak_menu, orch
from test_close_and_info import INHERITED, Menu


class StopBehindTheRow(unittest.TestCase):
    def setUp(self):
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        self.hold = Path(held.name) / "hold"
        self.hold.touch()                 # the stop waits until this is gone

    def test_the_popup_over_its_own_seat_goes_before_the_stop_ends(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega", hold=self.hold)
        menu.frame()
        menu.send(b"x")
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])
        self.assertNotIn("<stopped", menu.text())
        self.hold.unlink()
        menu.saw("<stopped omega>")       # and the stop goes on without it

    def test_a_stop_refused_after_the_popup_went_is_left_for_the_next_menu(self):
        menu = Menu(self, {"omega": "done"}, own="omega", hold=self.hold, refuse=True)
        menu.frame()
        menu.send(b"x")
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])
        self.hold.unlink()
        with patch.object(config, "STATE", menu.seats.parent / ".agentkit" / "state"):
            told = menu.until(lambda _: orch.job_notices(), "the refusal left behind")
            self.assertEqual(told, ["stop: omega refused"])
            self.assertEqual(orch.job_notices(), [])      # shown once

    def test_the_stop_process_leaves_its_refusal_as_a_notice(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "AGENTKIT_SESSION": "acme",
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test"})
        subprocess.run(ak_menu.teardown("fix-api", False), cwd=REPO, env=env, timeout=60,
                       check=True)
        with patch.object(config, "STATE", Path(home.name) / ".agentkit" / "state"):
            self.assertEqual(orch.job_notices(),
                             ["stop: owned by seat fix-api; a seat stops only its own runs"])

    def test_a_menu_collecting_while_a_notice_is_left_loses_none(self):
        state = Path(tempfile.mkdtemp(dir=self.hold.parent))
        collected, real_open = [], open

        def collect_once_opened(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if mode == "a":
                collected.extend(orch.job_notices())    # before its line is written
            return stream
        with patch.object(config, "STATE", state), patch.object(config, "ensure_dirs"), \
                patch("builtins.open", collect_once_opened):
            orch.leave_notice("stop: acme refused")
            collected.extend(orch.job_notices())
        self.assertEqual(collected, ["stop: acme refused"])


if __name__ == "__main__":
    unittest.main()

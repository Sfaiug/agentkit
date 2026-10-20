"""`x` takes a seat's row off the screen at once and stops the seat behind it: no read puts the row
back while the stop goes, a refused stop says why and gives the row back, and the popup over its
own seat goes before the stop ends, a refusal then left for the next menu.

Each test runs the real menu loop on a pty of its own through tests/test_close_and_info.py's
`Menu`, the stop a process of its own that waits while the test holds it; nothing here stops a
real seat, and the only processes signalled are the test's own children.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, menu as ak_menu, orch, terminal
from test_close_and_info import ENTER, INHERITED, Menu


def without(menu, name, after):
    """Where in the menu's output the first whole screen without `name` begins, after `after`."""
    def ready(text):
        for home in re.finditer(r"\x1b\[H", text[after:]):
            screen, ended, _ = text[after + home.end():].partition("\x1b[J")
            screen = terminal.ANSI.sub("", screen)
            if ended and menu.leave_key in screen and name not in screen:
                return after + home.start()
        return None
    return menu.until(ready, f"a screen without {name}")


class StopBehindTheRow(unittest.TestCase):
    def setUp(self):
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        self.hold = Path(held.name) / "hold"
        self.hold.touch()                 # the stop waits until this is gone

    def test_the_row_goes_before_the_stop_ends_and_no_read_brings_it_back(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, hold=self.hold)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        gone = without(menu, "omega", mark)
        self.assertNotIn("<stopped", menu.text())
        # a read while the stop is held: alpha's word moves with it, and omega stays off
        menu.seats.write_text(json.dumps({"alpha": "needs you", "omega": "done"}))
        moved = menu.seats.parent / ".agentkit" / "state" / "runs-moved"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.touch()
        menu.frame(lambda lines: any("alpha" in line and "needs you" in line for line in lines),
                   after=gone)
        self.assertNotIn("<stopped", menu.text())
        self.hold.unlink()
        menu.saw("<stopped omega>", after=gone)
        menu.leave()
        rest = terminal.ANSI.sub("", menu.text()[gone:]).replace("<stopped omega>", "")
        self.assertNotIn("omega", rest)

    def test_a_refused_stop_says_why_and_its_row_comes_back(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, refuse=True)
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        menu.saw("stop: omega refused", after=mark)
        back = menu.mark()
        menu.send(ENTER)
        menu.frame(lambda lines: any("omega" in line for line in lines), after=back)
        menu.leave()

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


if __name__ == "__main__":
    unittest.main()

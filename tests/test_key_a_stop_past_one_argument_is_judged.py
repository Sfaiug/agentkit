"""A Stop longer than one command argument is judged like any other.

A turn that moved a lot of output ends in a Stop no argument list would carry: Linux refuses a
single argument past 128 KiB.  A Claude seat whose plan has an open line and whose turn ends so,
with nothing recorded, has that Stop sent back with the harness's block decision; a seat with no
open line has it stand, and nothing is printed.  Black-box: the program `AK_BIN` names, its hooks
fired as Claude fires them (tests/fixtures/hookdrive.py) in a Home of tests/fixtures/akbin.py,
for seats of tests/fixtures/akseat.py that tmux lost, so only their records and plans are there.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import hookdrive
from fixtures.akbin import Home
from fixtures.akseat import Seat

# what the seat said last, a pasted log past what one argument holds, ending on no question
SAID = "The acme parser's log, as it ran:\n" + "acme parser: read one line\n" * 8000
assert len(SAID.encode()) > 128 * 1024


class AStopPastOneArgumentIsJudged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def stop(self, name, planned):
        """What the hooks printed back at a Stop of a turn the seat `name` was just given."""
        Seat(self.home, name, alive=False, planned=planned)
        began = self.hooks.fire("UserPromptSubmit", {"prompt": "Build the acme parser."},
                                seat=name)
        self.assertEqual(began.code, 0, began.err)
        fired = self.hooks.fire("Stop", {"background_tasks": [], "last_assistant_message": SAID},
                                seat=name)
        self.assertEqual(fired.code, 0, fired.err)
        return fired.said

    def test_open_work_goes_back(self):
        back, = self.stop("owes", planned=True)
        self.assertEqual(back.get("decision"), "block", back)
        self.assertIsInstance(back.get("reason"), str)
        self.assertTrue(back["reason"].strip(), back)

    def test_no_open_line_stands(self):
        self.assertEqual(self.stop("rests", planned=False), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

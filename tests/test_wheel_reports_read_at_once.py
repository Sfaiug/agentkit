"""A swipe is one key: every wheel report already sent is read with the first, as far as they all
go, so a screen draws once for them and a swipe past the end of a list is over when the finger
stops.  The real `terminal.read_key` on a pipe, the keyboard taken, the reports written whole
before it reads, as a trackpad's flood arrives."""

import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import terminal

Key = terminal.Key


def wheel(button, times=1):
    return f"\x1b[<{button};40;12M".encode() * times


class WheelReports(unittest.TestCase):
    def test_reports_sent_together_are_one_key(self):
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        with open(read, "rb", buffering=0) as stdin, patch.object(sys, "stdin", stdin), \
                patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                               _KEYED=b"", _NEXT=None, _HELD=None, _PRESSED=False, _AWAY=False,
                               _POINTER=None, _SPOTS={}):
            os.write(write, wheel(65, 300) + wheel(64, 20) + wheel(66, 5) + b"j" + wheel(65))
            key = terminal.read_key(1)
            self.assertEqual((key.name, terminal.step(key)), ("wheel-down", 280))
            self.assertEqual(terminal.read_key(1), Key("char", "j"))    # the key after, kept
            self.assertEqual(terminal.step(terminal.read_key(1)), 1)
            os.write(write, wheel(64, 3) + wheel(65, 3) + wheel(67))   # cancel out: no key
            self.assertIsNone(terminal.read_key(0))
            os.write(write, wheel(64) + b"\x1b[<0;9;4M\x1b[<0;9;4m")     # a click after, whole
            self.assertEqual(terminal.step(terminal.read_key(1)), -1)
            self.assertEqual(terminal.read_key(1), Key("click", "", 9, 4))


if __name__ == "__main__":
    unittest.main()

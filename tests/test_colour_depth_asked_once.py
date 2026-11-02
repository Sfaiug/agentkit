"""A frame asks for the colour depth for every cell it moves: the terminal is asked once, and a
changed answer still shows."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import terminal  # noqa: E402


class ColourDepthAskedOnce(unittest.TestCase):
    def test_asked_once_until_something_it_read_changes(self):
        out = Mock(isatty=Mock(return_value=True))
        with patch.object(sys, "stdout", out), \
                patch.dict(os.environ, {"TERM": "xterm-acme", "COLORTERM": "truecolor"}):
            os.environ.pop("NO_COLOR", None)
            self.assertEqual([terminal.colour_depth() for _ in range(5)], [24] * 5)
            self.assertEqual(out.isatty.call_count, 1)
            with patch.dict(os.environ, {"NO_COLOR": ""}):
                self.assertEqual(terminal.colour_depth(), 0)
            with patch.dict(os.environ, {"COLORTERM": ""}), patch("curses.setupterm"), \
                    patch("curses.tigetnum", return_value=8):
                self.assertEqual(terminal.colour_depth(), 8)
            with patch.object(sys, "stdout", Mock(isatty=Mock(return_value=False))):
                self.assertEqual(terminal.colour_depth(), 0)
            self.assertEqual(terminal.colour_depth(), 24)


if __name__ == "__main__":
    unittest.main()

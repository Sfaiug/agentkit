"""The clock at the top right is always whole, on every width and under every screen name."""

import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AGENTKIT_HOME", "/nonexistent-agentkit-home")

from agentkit import terminal  # noqa: E402


class ClockWhole(unittest.TestCase):
    def test_a_long_name_gives_way_to_the_clock(self):
        name = "fix-api-with-a-very-long-session-name models"
        for width in range(5, 131):
            with self.subTest(width=width):
                line = terminal.header_line(name, "13:02", width)
                self.assertTrue(line.endswith("13:02"), line)
                self.assertEqual(terminal.cells(line), terminal.layout_width(width))

    def test_a_narrower_terminal_than_the_clock_keeps_what_fits(self):
        self.assertEqual(terminal.cells(terminal.header_line("config", "13:02", 3)), 3)

    def test_every_line_is_cleared_before_it_is_written(self):
        # a clear after a line that fills the last column erases that column
        out = io.StringIO()
        with mock.patch.object(terminal, "taken", return_value=True), \
                mock.patch.object(terminal, "width", return_value=40), \
                mock.patch.object(sys, "stdout", out):
            terminal.frame("fix-api-with-a-long-name models", ["  a row"], "esc back")
        written = out.getvalue()
        lines = written.removeprefix("\033[H").removesuffix("\033[J").split("\n")[:-1]
        self.assertTrue(lines)
        for line in lines:
            self.assertTrue(line.startswith("\033[K"), repr(line))
            self.assertNotIn("\033[K", line[3:])
        self.assertTrue(terminal.plain(lines[0]).endswith(":" + lines[0][-2:]))


if __name__ == "__main__":
    unittest.main()

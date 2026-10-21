"""`ak -h` on a colour terminal shows its `internal:` line dim, and only that line.

The help is one screen: the menu and the commands an orchestrator uses, then one line naming the
commands the toolkit runs for itself, dim so a reader's eye passes over it.  On an eight-colour
terminal dim is the terminal's own faint style.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py with a terminal on its stdout, and this test fails
against `/bin/false`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

INTERNAL = ("orch", "worker", "hand-in", "watch", "update", "macbridge", "attach", "doctor")
COLOUR = {"TERM": "xterm", "NO_COLOR": None, "COLORTERM": None}   # eight colours, per terminfo


class HelpInternalLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def on_terminal(self, *args):
        """Run ak with a terminal on stdout, as a person's shell does, and return what it drew."""
        reader, terminal = os.openpty()
        try:
            proc = subprocess.Popen([AK, *args], stdin=subprocess.DEVNULL, stdout=terminal,
                                    stderr=subprocess.PIPE, cwd=self.home.path,
                                    env=self.home._env(COLOUR), start_new_session=True)
            os.close(terminal)
            terminal = None
            drawn = b""
            while True:
                try:
                    chunk = os.read(reader, 4096)
                except OSError:   # the terminal's other end closed with the program
                    break
                if not chunk:
                    break
                drawn += chunk
            self.assertEqual(proc.wait(timeout=60), 0, proc.stderr.read())
            proc.stderr.close()
        finally:
            for fd in (reader, terminal):
                if fd is not None:
                    os.close(fd)
        return drawn.decode().replace("\r\n", "\n")

    def test_the_internal_line_alone_is_dim(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag):
                lines = self.on_terminal(flag).splitlines()
                internal = [line for line in lines if "internal:" in line]
                self.assertEqual(len(internal), 1, lines)
                match = re.fullmatch(r"\x1b\[2m(internal:.*)\x1b\[0m", internal[0])
                self.assertIsNotNone(match, internal[0])
                for command in INTERNAL:
                    self.assertRegex(match[1], rf"(?<![\w-]){re.escape(command)}(?![\w-])")
                others = [line for line in lines if line not in internal]
                self.assertTrue(others)
                self.assertFalse([line for line in others if "\x1b" in line])


if __name__ == "__main__":
    unittest.main()

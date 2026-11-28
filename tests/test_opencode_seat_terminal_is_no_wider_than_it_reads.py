"""A seat's OpenCode is told a terminal no wider than 120 columns, where it draws no sidebar."""

import fcntl
import os
from pathlib import Path
import pty
import struct
import subprocess
import sys
import termios
import unittest

WRAPPER = Path(__file__).resolve().parents[1] / "tools/idle-compact.py"
SIZE = 'while [ "$(stty size)" = "0 0" ]; do sleep 0.05; done; stty size'   # 0 0: not told yet


class OpenCodeSeatTerminal(unittest.TestCase):
    def told(self, harness, columns):     # what the seat wrapper tells a harness in that window
        owner, window = pty.openpty()
        fcntl.ioctl(window, termios.TIOCSWINSZ, struct.pack("4H", 50, columns, 0, 0))
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "AGENTKIT_SESSION")}
        subprocess.run([sys.executable, WRAPPER, "--harness", harness, "--", "sh", "-c", SIZE],
                       stdin=window, stdout=window, env=env, check=True, timeout=30)
        return os.read(owner, 1024).decode().split()

    def test_a_window_wider_than_opencode_reads_is_told_as_120_columns(self):
        self.assertEqual(self.told("opencode", 240), ["50", "120"])
        self.assertEqual(self.told("opencode", 100), ["50", "100"])
        self.assertEqual(self.told("claude", 240), ["50", "240"])    # no `widest` of its own


if __name__ == "__main__":
    unittest.main()

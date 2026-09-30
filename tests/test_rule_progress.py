"""The rule under the header is ak's one progress indicator: a start update fills it under
`agentkit · updating`, one step at a time, with no bar of its own; a screen whose content is
still being fetched after 150 ms has a bright segment glide along it until it lands, and one
fetched sooner shows nothing; Esc during a glide goes back within 100 ms.

The update runs in-process against a temporary HOME, every command it would run answered by a
fake `subprocess.run`, so no checkout moves.  The glide runs a project's feature switches screen
in a child process on a pty of its own, the project's `list` a fake that sleeps as long as the
test says; nothing reaches a real project, seat or the owner's ~/.agentkit, and the only process
signalled is the test's own child.
"""

from contextlib import redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, update  # noqa: E402

# The child: the real feature switches screen and key reader over a `list` that takes RULE_LIST
# seconds; it says when the screen has gone back.
CHILD = r"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["RULE_REPO"])
from agentkit import menu, terminal

def features_run(checkout, *words):
    time.sleep(float(os.environ["RULE_LIST"]))
    return [{"id": "dark", "name": "Dark mode", "you": False, "everyone": False}], ""

menu.features_run = features_run
keyboard = terminal.Keyboard()
keyboard.take()
menu.show_features(Path.home() / "code" / "ACME")
keyboard.give()
print("<back>", flush=True)
"""
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")
GLIDE = re.compile(r"\x1b\[2;\d+H\x1b\[[0-9;]*m━")   # a lit cell written on the rule's row


class Screen:
    """The child on an 80x24 pty: what it wrote, and when each part of it arrived."""

    def __init__(self, case, seconds):
        home = tempfile.TemporaryDirectory(prefix="rule-progress-")
        case.addCleanup(home.cleanup)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "COLORTERM": "truecolor",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0",
                    "AK_MAX_RUNS": "0", "RULE_REPO": str(REPO), "RULE_LIST": str(seconds)})
        self.case, self.output, self.arrived = case, b"", []
        self.lock = threading.Lock()
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD], stdin=self.slave,
                                     stdout=self.slave, stderr=self.slave, env=env,
                                     start_new_session=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        case.addCleanup(self.close)

    def _read(self):
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.output += chunk
                self.arrived.append((time.monotonic(), len(self.output)))

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()          # this test's own child, and nothing else
        self.proc.wait(10)
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass
        self.reader.join(5)

    def text(self):
        with self.lock:
            return self.output.decode("utf-8", "replace")

    def when(self, pattern, timeout=15):
        """When what `pattern` matches first reached the pty, waiting for it."""
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                found = re.search(pattern, self.output.decode("utf-8", "replace"))
                if found:
                    end = len(self.output.decode("utf-8", "replace")[:found.end()].encode())
                    return next(at for at, size in self.arrived if size >= end)
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {pattern!r}:\n{self.text()[-2000:]!r}")
            time.sleep(0.01)


class RuleProgress(unittest.TestCase):
    def test_a_start_update_fills_the_rule_under_its_header_word(self):
        home = tempfile.TemporaryDirectory(prefix="rule-progress-")
        self.addCleanup(home.cleanup)
        ran, out = [], io.StringIO()

        def run(cmd, **kwargs):
            ran.append(cmd[3] if cmd[0] == "git" else Path(cmd[0]).name)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch.dict(os.environ, {"HOME": home.name, "COLUMNS": "60"}), \
                patch.object(update, "agentkit_dir", return_value=config.REPO), \
                patch.object(update, "left_as_is", return_value=""), \
                patch.object(update, "behind", return_value=True), \
                patch.object(update, "agentkit_version", return_value="abc1234 · 2026-09-30"), \
                patch.object(update.subprocess, "run", run), redirect_stdout(out):
            menu.update_first()
        self.assertEqual(ran, ["fetch", "pull", "install.sh"])
        lines = out.getvalue().splitlines()
        frames = [(lines[n - 1], line) for n, line in enumerate(lines) if set(line) <= set("━─")
                  and line]
        self.assertEqual([header[:19] for header, _ in frames], ["agentkit · updating"] * 4)
        self.assertEqual([rule.count("━") for _, rule in frames], [0, 20, 40, 60])
        self.assertEqual({len(rule) for _, rule in frames}, {60})
        for other in ("█", "░", "#", "/3", "fetch", "pull", "install", "Updating"):
            self.assertNotIn(other, out.getvalue())       # no bar and no step but the rule's

    def test_a_two_second_list_glides_and_lands(self):
        screen = Screen(self, 2)
        opened = screen.when("asking for its features")
        glided = screen.when(GLIDE.pattern)
        self.assertGreater(glided - opened, 0.1)            # nothing for the first 150 ms
        screen.when("Dark mode")
        text = screen.text()
        landed = text.rindex("\x1b[H", 0, text.index("Dark mode"))
        self.assertIn("─" * 80, text[landed:])              # the rule still once it landed
        self.assertNotIn("━", text[landed:])
        self.assertGreater(len(GLIDE.findall(text[:landed])), 10)    # moving, not one frame
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_a_fifty_millisecond_list_shows_nothing(self):
        screen = Screen(self, 0.05)
        opened = screen.when("asking for its features")
        landed = screen.when("Dark mode")
        self.assertLess(landed - opened, 0.5)                # within a frame, not a second
        time.sleep(0.3)
        self.assertNotIn("━", screen.text())
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_esc_during_a_glide_goes_back_within_100_ms(self):
        screen = Screen(self, 2)
        screen.when(GLIDE.pattern)
        pressed = time.monotonic()
        os.write(screen.master, b"\x1b")
        self.assertLess(screen.when("<back>") - pressed, 0.1)
        self.assertEqual(screen.proc.wait(10), 0, screen.text()[-2000:])
        self.assertNotIn("Dark mode", screen.text())         # the list had not landed


if __name__ == "__main__":
    unittest.main()

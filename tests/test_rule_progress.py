"""The rule under the header is ak's one progress indicator: a start update fills it under
`agentkit · updating`, one step at a time, with no bar of its own; a screen whose content is
still being fetched after 150 ms has a bright segment glide along it until it lands, and one
fetched sooner shows nothing -- a list asked again under rows already drawn, and a `set`, as
much as a first list; Esc during a glide goes back within 100 ms, and a `set` it leaves behind
never draws over a later one.  A screen waiting on a fetch draws itself again on a resize, moves
its rule on the clock's frames however fast keys come, and goes back on a click on `esc back`.

The update runs in-process against a temporary HOME, every command it would run answered by a
fake `subprocess.run`, so no checkout moves.  The glide runs a project's feature switches screen
in a child process on a pty of its own, the project's `list` and `set` a fake that sleeps as
long as the test says, and so does the wait; nothing reaches a real project, seat or the owner's
~/.agentkit, and the only process signalled is the test's own child.
"""

from contextlib import redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import re
import signal
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
from agentkit import config, menu, motion, terminal, update  # noqa: E402

# The child: the real feature switches screen and key reader, opened RULE_OPENS times, over a
# `list` that takes RULE_LIST seconds, asked again every RULE_TICK, and `set`s that take each of
# RULE_SET in turn, answering the row as each left it; it says when the screen has gone back.
# With RULE_WAIT it is a screen waiting that long on a fetch instead.
CHILD = r"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["RULE_REPO"])
from agentkit import menu, terminal

server = {"id": "dark", "name": "Dark mode", "you": False, "everyone": False}
sets = [float(seconds) for seconds in os.environ["RULE_SET"].split(",")]

def features_run(checkout, *words):
    if words[0] == "list":
        time.sleep(float(os.environ["RULE_LIST"]))
        return [dict(server)], ""
    server[words[2]] = words[3] == "on"
    row = dict(server)
    time.sleep(sets.pop(0) if sets else 0)
    print(f"<set {words[2]} {words[3]} answered>", flush=True)
    return row, ""

menu.features_run, menu.TICK = features_run, float(os.environ["RULE_TICK"])
keyboard = terminal.Keyboard()
keyboard.take()
if os.environ["RULE_WAIT"]:
    try:
        menu.waited(lambda: time.sleep(float(os.environ["RULE_WAIT"])), "config · acme",
                    ["", "  a line"])
    except menu.Back:
        print("<went back>", flush=True)
for _ in range(int(os.environ["RULE_OPENS"])):
    menu.show_features(Path.home() / "code" / "ACME")
    print("<back>", flush=True)
keyboard.give()
"""
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")
GLIDE = re.compile(r"\x1b\[2;\d+H\x1b\[[0-9;]*m━")   # a lit cell written on the rule's row


class Screen:
    """The child on an 80x24 pty: what it wrote, and when each part of it arrived."""

    def __init__(self, case, seconds=0, tick=10, flip=0, opens=1, wait=""):
        home = tempfile.TemporaryDirectory(prefix="rule-progress-")
        case.addCleanup(home.cleanup)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "COLORTERM": "truecolor",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0",
                    "AK_MAX_RUNS": "0", "RULE_REPO": str(REPO), "RULE_LIST": str(seconds),
                    "RULE_TICK": str(tick), "RULE_SET": str(flip), "RULE_OPENS": str(opens),
                    "RULE_WAIT": str(wait)})
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

    def when(self, pattern, after=0, timeout=15):
        """When what `pattern` matches first reached the pty past `after` characters, waiting
        for it."""
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                found = re.compile(pattern).search(self.output.decode("utf-8", "replace"), after)
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

    def test_a_list_asked_again_under_its_rows_glides_too(self):
        screen = Screen(self, 0.5, tick=1)
        screen.when("Dark mode")
        drawn = screen.text().index("Dark mode")
        screen.when(GLIDE.pattern, after=drawn)              # the next list, a second on
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_a_slow_set_glides_and_esc_goes_back_from_it(self):
        screen = Screen(self, 0, flip=2)
        screen.when("Dark mode")
        after, entered = len(screen.text()), time.monotonic()
        os.write(screen.master, b"\r")
        self.assertGreater(screen.when(GLIDE.pattern, after) - entered, 0.1)
        pressed = time.monotonic()
        os.write(screen.master, b"\x1b")
        self.assertLess(screen.when("<back>") - pressed, 0.1)
        self.assertEqual(screen.proc.wait(10), 0, screen.text()[-2000:])

    def test_a_set_left_behind_by_esc_never_draws_over_a_later_one(self):
        screen = Screen(self, 0, flip="2,0", opens=2)
        screen.when("Dark mode")
        os.write(screen.master, b"\r")                  # `you on`, answered in two seconds
        screen.when(GLIDE.pattern)
        os.write(screen.master, b"\x1b")
        screen.when("<back>")
        screen.when("Dark mode", after=screen.text().index("<back>"))    # open again
        os.write(screen.master, b"\x1b[C\r")           # `everyone on`, answered at once
        screen.when("<set everyone on answered>")
        screen.when("<set you on answered>")            # with `everyone` still off in its row
        time.sleep(1.5)                                  # a draw since, a second at a time
        text = terminal.ANSI.sub("", screen.text().split("\x1b[H")[-1].split("\x1b[J")[0])
        line = next(line for line in text.splitlines() if "Dark mode" in line)
        self.assertEqual([mark for mark in line.split() if mark in "●○"], ["●", "●"], line)
        os.write(screen.master, b"\x1b")
        self.assertEqual(screen.proc.wait(10), 0, screen.text()[-2000:])

    def test_a_wait_keeps_to_the_clock_redraws_on_a_resize_and_a_click_goes_back(self):
        screen = Screen(self, wait=30, opens=0)
        screen.when(GLIDE.pattern)
        began = time.monotonic()
        for _ in range(100):                             # keys the wait lets go, every 5 ms
            os.write(screen.master, b"x")
            time.sleep(0.005)
        with screen.lock:
            sizes = [0] + [size for _, size in screen.arrived]
            frames = sum(b"\x1b[2;" in screen.output[before:size]
                         for (at, size), before in zip(screen.arrived, sizes) if at >= began)
        self.assertLessEqual(frames, 2 + (time.monotonic() - began) / motion.FRAME)
        after = len(screen.text())
        fcntl.ioctl(screen.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
        os.kill(screen.proc.pid, signal.SIGWINCH)      # the test's own child
        screen.when(r"\x1b\[H\x1b\[Kagentkit · config · acme", after)
        drawn = screen.text().rindex("\x1b[H")
        self.assertRegex(screen.text()[drawn:], r"[^─]─{40}\x1b")     # the rule 40 wide
        screen.when(GLIDE.pattern, drawn)
        columns = re.findall(r"\x1b\[2;(\d+)H", screen.text()[drawn:])
        self.assertLessEqual(max(map(int, columns)), 40)
        os.write(screen.master, b"\x1b[<0;4;6M\x1b[<0;4;6m")   # a click on `esc back`
        screen.when("<went back>")
        self.assertEqual(screen.proc.wait(10), 0, screen.text()[-2000:])


if __name__ == "__main__":
    unittest.main()

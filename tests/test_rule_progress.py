"""The rule under the header is ak's one progress indicator: a start update fills it under
`agentkit · updating`, one step at a time, with no bar of its own; a screen whose content is
still being fetched after 150 ms has a bright segment glide along it until it lands, and one
fetched sooner shows nothing -- a list asked again under rows already drawn, and a `set`, as
much as a first list, and one landing as the screen is drawn is drawn at once; Esc during a glide
goes back within 100 ms, and a `set` it leaves behind never draws over a later one.  A screen
waiting on a fetch draws itself again on a resize, moves its rule on the clock's frames however
fast keys come, and goes back on a click on `esc back`; a `Models` list, waiting on a catalog at
80 columns, is laid out again at 40: every line fits, and a click on the `esc back` drawn goes
back.

The update's progress callback runs against a temporary HOME, every command answered by a
fake `subprocess.run`, so no checkout moves.  The glide runs a project's feature switches screen
in a child process on a pty of its own, the project's `list` and `set` a fake that takes as
long as the test says, and so do the wait and a catalog, over a config built in the child.  The
child's clock moves only as a wait of its own runs out, and it says so, so what a test measures
is what the screen did however the host runs it; nothing reaches a real project, seat or the
owner's ~/.agentkit, and the only process signalled is the test's own child.
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

# Both children's time: the real screens, clock and key reader over a clock that moves only by
# the waits that run out, each saying where it stands now, and a clock's every frame said too;
# with RULE_HOLD no wait runs out from the first lit cell until a key is read.  A list due by
# then has landed before the clock goes on, one that takes no time as the first draw is out.
CLOCK = r"""
import os, sys, threading, time
sys.path.insert(0, os.environ["RULE_REPO"])
from agentkit import menu, motion, terminal


class Waited:
    now = time.monotonic()

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


menu.time = motion.time = terminal.time = waited = Waited()
print(f"<now {waited.now}>", flush=True)
LIST, hold, held = float(os.environ["RULE_LIST"]), bool(os.environ["RULE_HOLD"]), False
drawn = threading.Event()


def until(due):
    while waited.now < due:
        time.sleep(0.001)


def landed():
    while any(entry["going"] and waited.now >= entry["asked"] + LIST
              for entry in menu._SWITCHES.values()):
        time.sleep(0.001)


def read_key(timeout=None, wake=None, read=terminal.read_key):
    global held
    timeout, began = None if held else timeout, time.monotonic()
    key = read(timeout, wake)
    held = held and key is None
    if key is None and timeout and time.monotonic() >= began + timeout:
        waited.now += timeout       # it ran out: no key, no news
        print(f"<now {waited.now}>", flush=True)
        landed()
    return key


def frame(*args, draw=terminal.frame, **more):
    spots = draw(*args, **more)
    drawn.set()
    landed()
    return spots


def clock_frame(clock, write=motion.Clock.frame):
    global held
    out = write(clock)
    held = held or hold and "━" in out
    return "<frame>" + out


terminal.read_key, terminal.frame, motion.Clock.frame = read_key, frame, clock_frame
"""
# The child: the real feature switches screen and key reader, opened RULE_OPENS times, over a
# `list` that takes RULE_LIST seconds, asked again every RULE_TICK, and `set`s that take each of
# RULE_SET in turn, none answered before the last is asked, answering the row as each left it;
# it says when each has landed and when the screen has gone back.  With RULE_WAIT it is a screen
# waiting on a fetch that never lands instead.
CHILD = CLOCK + r"""
from pathlib import Path

server = {"id": "dark", "name": "Dark mode", "you": False, "everyone": False}
sets = [float(seconds) for seconds in os.environ["RULE_SET"].split(",")]

def features_run(checkout, *words):
    if words[0] == "list":
        drawn.wait()
        until(menu._SWITCHES[str(checkout)]["asked"] + LIST)
        return [dict(server)], ""
    server[words[2]] = words[3] == "on"
    row = dict(server)
    until(waited.now + (sets.pop(0) if sets else 0))
    while sets:
        time.sleep(0.001)
    return row, ""

def features_flip(checkout, feature, column, flip=menu.features_flip):
    note = flip(checkout, feature, column)
    print(f"<{menu.FEATURES_HEADS[column]} landed>", flush=True)
    return note

menu.features_run, menu.features_flip = features_run, features_flip
menu.TICK = float(os.environ["RULE_TICK"])
keyboard = terminal.Keyboard()
keyboard.take()
if os.environ["RULE_WAIT"]:
    try:
        menu.waited(threading.Event().wait, "config · acme", lambda: ["", "  a line"])
    except menu.Back:
        print("<went back>", flush=True)
for _ in range(int(os.environ["RULE_OPENS"])):
    menu.show_features(Path.home() / "code" / "ACME")
    print("<back>", flush=True)
keyboard.give()
"""
# The child for a catalog wait: `Models`, over a config whose one model runs an id 59
# characters long, and a catalog that never answers; it says when it has gone back.
CATALOG = CLOCK + r"""
from agentkit import config

ID = "acme-model-" + "x" * 48
config.catalog = lambda harness, cfg=None: threading.Event().wait()
cfg = {"defaults": {"orchestrator": "acme", "workers": ["acme"]},
       "models": {"acme": {"harness": "claude", "model": ID, "effort": "high",
                           "provider": "anthropic"}},
       "providers": {"anthropic": {"mode": "subscription"}}}
keyboard = terminal.Keyboard()
keyboard.take()
menu.models_page(cfg, keyboard)
print("<went back>", flush=True)
keyboard.give()
"""
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")
GLIDE = re.compile(r"\x1b\[2;\d+H\x1b\[[0-9;]*m━")   # a lit cell written on the rule's row
HUNG = 120      # seconds with no answer: a child importing cold on a loaded host takes tens of them


def clock_at(text):
    """What the child's clock read as it wrote the end of `text`, all it had written by then."""
    return float(re.findall(r"<now ([\d.]+)>", text)[-1])


class Screen:
    """The child on an 80x24 pty, and what it wrote."""

    def __init__(self, case, seconds=0, tick=10, flip=0, opens=1, wait=False, child=CHILD,
                 hold=False):
        home = tempfile.TemporaryDirectory(prefix="rule-progress-")
        case.addCleanup(home.cleanup)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "COLORTERM": "truecolor",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0",
                    "AK_MAX_RUNS": "0", "RULE_REPO": str(REPO), "RULE_LIST": str(seconds),
                    "RULE_TICK": str(tick), "RULE_SET": str(flip), "RULE_OPENS": str(opens),
                    "RULE_WAIT": "1" if wait else "", "RULE_HOLD": "1" if hold else ""})
        self.case, self.output = case, b""
        self.proc = subprocess.Popen([sys.executable, "-c", child], stdin=self.slave,
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
            self.output += chunk

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()          # this test's own child, and nothing else
        self.proc.wait(HUNG)
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass
        self.reader.join(5)

    def text(self):
        return self.output.decode("utf-8", "replace")

    def when(self, pattern, after=0):
        """What the child's clock read as what `pattern` matches was first written past `after`
        characters, waiting for it."""
        deadline = time.monotonic() + HUNG
        while True:
            text = self.text()
            found = re.compile(pattern).search(text, after)
            if found:
                return clock_at(text[:found.end()])
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {pattern!r}:\n{self.text()[-2000:]!r}")
            time.sleep(0.01)

    def draw(self, after=0):
        """Where the next whole draw past `after` characters starts and its lines, waiting for
        it."""
        self.when(r"\x1b\[H\x1b\[K", after)
        start = self.text().index("\x1b[H\x1b[K", after)
        self.when(r"\x1b\[J", start)
        text = self.text()
        lines = terminal.ANSI.sub("", text[start:text.index("\x1b[J", start)]).split("\r\n")
        return start, lines[:-1]


def click_back_at_forty(case, screen):
    """The pty made 40 columns wide under a screen waiting on a fetch: every line of the screen
    it draws again fits, and `esc back` is clicked where it is drawn."""
    after = len(screen.text())
    fcntl.ioctl(screen.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
    os.kill(screen.proc.pid, signal.SIGWINCH)      # the test's own child
    _, lines = screen.draw(after)
    for line in lines:
        case.assertLessEqual(terminal.cells(line), 40, lines)
    row, line = next((row, line) for row, line in enumerate(lines, 1) if "esc back" in line)
    column = line.index("esc") + 2
    os.write(screen.master, f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m".encode())


class RuleProgress(unittest.TestCase):
    def test_a_start_update_fills_the_rule_under_its_header_word(self):
        home = tempfile.TemporaryDirectory(prefix="rule-progress-")
        self.addCleanup(home.cleanup)
        ran, out = [], io.StringIO()

        def run(cmd, **kwargs):     # origin/main is ahead and has no tests/live.sh
            ran.append(cmd[3] if cmd[0] == "git" else Path(cmd[0]).name)
            return subprocess.CompletedProcess(cmd, int(cmd[3:4] == ["cat-file"]),
                                               "acme\n" if cmd[3:4] == ["rev-parse"] else "", "")

        def progress(done, total):
            with redirect_stdout(out):
                terminal.frame("updating", (), "", done / total)

        with patch.dict(os.environ, {"HOME": home.name, "COLUMNS": "60"}), \
                patch.object(update, "agentkit_dir", return_value=config.REPO), \
                patch.object(update, "left_as_is", return_value=""), \
                patch.object(config, "ensure_dirs"), patch.object(config, "TMP", Path(home.name)), \
                patch.object(config, "STATE", Path(home.name)), \
                patch.object(update.versions, "switch", lambda *_: ran.append("switch") or ""), \
                patch.object(update.subprocess, "run", run), redirect_stdout(io.StringIO()):
            update.update_agentkit(progress)
        self.assertEqual(ran, ["fetch", "rev-parse", "cat-file", "switch", "install.sh"])
        lines = out.getvalue().splitlines()
        frames = [(lines[n - 1], line) for n, line in enumerate(lines) if set(line) <= set("━─")
                  and line]
        self.assertEqual([header[:19] for header, _ in frames], ["agentkit · updating"] * 4)
        self.assertEqual([rule.count("━") for _, rule in frames], [0, 20, 40, 60])
        self.assertEqual({len(rule) for _, rule in frames}, {60})
        for other in ("█", "░", "#", "/3", "fetch", "merge", "install", "Updating"):
            self.assertNotIn(other, out.getvalue())       # no bar and no step but the rule's

    def test_a_two_second_list_glides_and_lands(self):
        screen = Screen(self, 2)
        opened = screen.when("asking for its features")
        glided = screen.when(GLIDE.pattern)
        self.assertGreaterEqual(glided - opened, 0.15)      # nothing for the first 150 ms
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
        screen.when(r"\x1b\[H", screen.text().index("Dark mode"))    # the draw a second on
        self.assertNotIn("━", screen.text())
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_a_list_landing_as_the_screen_is_drawn_is_drawn_at_once(self):
        screen = Screen(self, 0)
        opened = screen.when("asking for its features")
        self.assertLess(screen.when("Dark mode") - opened, 0.5)
        self.assertNotIn("━", screen.text())
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_esc_during_a_glide_goes_back_within_100_ms(self):
        screen = Screen(self, 2, hold=True)
        pressed = screen.when(GLIDE.pattern)
        os.write(screen.master, b"\x1b")
        self.assertLess(screen.when("<back>") - pressed, 0.1)
        self.assertEqual(screen.proc.wait(HUNG), 0, screen.text()[-2000:])
        self.assertNotIn("Dark mode", screen.text())         # the list had not landed

    def test_a_list_asked_again_under_its_rows_glides_too(self):
        screen = Screen(self, 0.5, tick=1)
        screen.when("Dark mode")
        drawn = screen.text().index("Dark mode")
        screen.when(GLIDE.pattern, after=drawn)              # the next list, a second on
        os.write(screen.master, b"\x1b")
        screen.when("<back>")

    def test_a_slow_set_glides_and_esc_goes_back_from_it(self):
        screen = Screen(self, 0, flip=2, hold=True)
        screen.when("Dark mode")
        before = screen.text()
        os.write(screen.master, b" ")
        pressed = screen.when(GLIDE.pattern, len(before))
        self.assertGreaterEqual(pressed - clock_at(before), 0.15)
        os.write(screen.master, b"\x1b")
        self.assertLess(screen.when("<back>") - pressed, 0.1)
        self.assertEqual(screen.proc.wait(HUNG), 0, screen.text()[-2000:])

    def test_a_set_left_behind_by_esc_never_draws_over_a_later_one(self):
        screen = Screen(self, 0, flip="2,0", opens=2)
        screen.when("Dark mode")
        os.write(screen.master, b" ")                  # `you on`, answered in two seconds
        screen.when(GLIDE.pattern)
        os.write(screen.master, b"\x1b")
        screen.when("<back>")
        screen.when("Dark mode", after=screen.text().index("<back>"))    # open again
        os.write(screen.master, b"\x1b[C ")            # `everyone on`, answered at once
        screen.when("<everyone landed>")
        screen.when("<you landed>")                     # with `everyone` still off in its row
        # the draw under way as it landed may have read the rows before it, the next did not
        under_way, _ = screen.draw(screen.text().index("<you landed>"))
        _, lines = screen.draw(under_way + 1)
        line = next(line for line in lines if "Dark mode" in line)
        self.assertEqual([mark for mark in line.split() if mark in "●○"], ["●", "●"], line)
        os.write(screen.master, b"\x1b")
        self.assertEqual(screen.proc.wait(HUNG), 0, screen.text()[-2000:])

    def test_a_wait_keeps_to_the_clock_redraws_on_a_resize_and_a_click_goes_back(self):
        screen = Screen(self, wait=True, opens=0)
        screen.when(GLIDE.pattern)
        before = screen.text()
        for _ in range(100):                             # keys the wait lets go, every 5 ms
            os.write(screen.master, b"x")
            time.sleep(0.005)
        text = screen.text()
        self.assertLessEqual(text[len(before):].count("<frame>"),
                             2 + (clock_at(text) - clock_at(before)) / motion.FRAME)
        after = len(text)
        fcntl.ioctl(screen.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
        os.kill(screen.proc.pid, signal.SIGWINCH)      # the test's own child
        screen.when(r"\x1b\[H\x1b\[Kagentkit · config · acme", after)
        drawn = screen.text().rindex("\x1b[H")
        screen.when(r"[^─]─{40}\x1b", drawn)          # the rule 40 wide, once it arrives
        screen.when(GLIDE.pattern, drawn)
        columns = re.findall(r"\x1b\[2;(\d+)H", screen.text()[drawn:])
        self.assertLessEqual(max(map(int, columns)), 40)
        os.write(screen.master, b"\x1b[<0;4;6M\x1b[<0;4;6m")   # a click on `esc back`
        screen.when("<went back>")
        self.assertEqual(screen.proc.wait(HUNG), 0, screen.text()[-2000:])

    def test_a_models_list_waited_on_is_laid_out_again_at_forty_columns(self):
        screen = Screen(self, opens=0, child=CATALOG)
        screen.when("Claude Code")
        os.write(screen.master, b"\r")                  # claude's list: its catalog is asked
        screen.when(GLIDE.pattern)
        click_back_at_forty(self, screen)
        screen.when("not read: esc and open it again")  # the list, saying so
        after = len(screen.text())
        os.write(screen.master, b"\x1b")                # the list closed, the page drawn again
        screen.when(r"\x1b\[J", after)
        os.write(screen.master, b"\x1b")
        screen.when("<went back>")
        self.assertEqual(screen.proc.wait(HUNG), 0, screen.text()[-2000:])


if __name__ == "__main__":
    unittest.main()

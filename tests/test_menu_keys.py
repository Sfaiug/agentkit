"""On a terminal the main menu reads a key at a time: a key acts at once, a highlight moves with
the arrows and stays on its seat, Enter and a click open, and the terminal comes back exactly.

Each test runs `menu.loop` in a child process on a pty of its own, with the seat listing, the
seats' words, the usage rows and the probe faked, and opening a seat reduced to a line saying
which one.  Nothing here starts a session, a tmux server or a probe; the only process signalled
is the test's own child.
"""

from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
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
from agentkit import terminal

# The child: the real loop, draw and key reader; fakes for what a seat is and what opening does.
CHILD = r"""
import json, os, re, sys, termios, time
sys.path.insert(0, os.environ["MENU_KEYS_REPO"])
from pathlib import Path
from agentkit import config, menu, orch

SEATS = Path(os.environ["MENU_KEYS_SEATS"])
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0} for name in json.loads(SEATS.read_text())]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "", "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
menu.TICK = float(os.environ["MENU_KEYS_TICK"])
drawing, real_draw = [0], menu.draw

def draw(*args, **kwargs):
    drawing[0] += 1
    print(f"<drawing {drawing[0]}>", end="", flush=True)
    time.sleep(float(os.environ["MENU_KEYS_SLOW"]))    # a draw a key can land in the middle of
    return real_draw(*args, **kwargs)

def open_session(cfg, session, dry_run):
    print(f"<opened {session['name']}>", flush=True)
    if os.environ["MENU_KEYS_SESSION_READS"] == "1":    # a session: whatever he types next is its
        # A seat is a tmux client, and tmux reads a mouse report as the mouse event it is and
        # hands the pane what was typed; this stands in for that and says what the pane got.
        typed = re.sub(rb"\x1b\[<\d+;\d+;\d+[Mm]", b"", os.read(0, 1024))
        print(f"<session read {typed!r}>", flush=True)

def select(cfg, providers, prompting=False):
    cooked = bool(termios.tcgetattr(0)[3] & termios.ICANON) if os.isatty(0) else None
    print(f"<lines {cooked}>", flush=True)
    print(f"<answered {menu.read('Orchestrator [fable]: ', 'q')!r}>", flush=True)
    return orch.BACK

menu.draw, menu.open_session, orch.select = draw, open_session, select
sys.exit(menu.loop(config.load(), dry_run=True))
"""
DOWN, ENTER = b"\x1b[B", b"\r"
GIVEN = ("\x1b[?1006l", "\x1b[?1000l", "\x1b[?25h", "\x1b[?1049l")


class Menu:
    """One child menu on a pty: what it wrote so far, and keys sent to it."""

    def __init__(self, case, seats, tick=10.0, slow=0.0, rows=40, cols=100, session_reads=False):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="menu-keys-")
        case.addCleanup(home.cleanup)
        self.seats = Path(home.name) / "seats.json"
        self.set_seats(seats)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.before = termios.tcgetattr(self.slave)
        env = {key: value for key, value in os.environ.items()
               if key not in ("NO_COLOR", "COLUMNS", "LINES", "TMUX")}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "MENU_KEYS_REPO": str(REPO), "MENU_KEYS_SEATS": str(self.seats),
                    "MENU_KEYS_TICK": str(tick), "MENU_KEYS_SLOW": str(slow),
                    "MENU_KEYS_SESSION_READS": "1" if session_reads else "0"})
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD], stdin=self.slave,
                                     stdout=self.slave, stderr=self.slave, env=env,
                                     start_new_session=True)
        self.output, self.lock = b"", threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        case.addCleanup(self.close)

    def _read(self):
        while True:
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.output += chunk

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

    def set_seats(self, names):
        self.seats.write_text(json.dumps(names))

    def text(self):
        with self.lock:
            return self.output.decode("utf-8", "replace")

    def until(self, ready, what, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            text = self.text()
            found = ready(text)
            if found:
                return found
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {what}:\n{text[-3000:]!r}")
            time.sleep(0.02)

    def saw(self, *texts, after=0):
        return self.until(lambda text: all(t in text[after:] for t in texts) and text,
                          " & ".join(texts))

    def send(self, keys):
        os.write(self.master, keys)

    def frame(self, where=None, after=0):
        """The lines of the last whole menu drawn, as the screen shows them; row 1 first."""
        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written, or a sub-screen's
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if any("q leave" in line for line in lines):
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, "a drawn menu")

    def highlighted(self, lines):
        marked = [line for line in lines if line.startswith("›")]
        self.case.assertEqual(len(marked), 1, lines)
        return marked[0]

    def click(self, col, row, held=0.0):
        """The left button down and up at `col`, `row`, as a terminal in mode 1006 reports it."""
        self.send(f"\x1b[<0;{col};{row}M".encode())
        time.sleep(held)
        self.send(f"\x1b[<0;{col};{row}m".encode())

    def resize(self, rows, cols):
        """What a terminal that turns does: a new size, then SIGWINCH to the child alone."""
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)

    def leave(self):
        self.send(b"q")
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


class MenuKeys(unittest.TestCase):
    def test_one_n_typed_through_a_redraw_opens_the_new_session_screen(self):
        """The owner's report: `n` typed while the screen redraws, then `not a key: 'nn'`."""
        menu = Menu(self, ["seat-a"], tick=0.2, slow=0.3)
        menu.saw("<drawing 2>")                 # the clock's redraw, the screen being cleared
        menu.send(b"n")                         # once, no Enter, in the middle of that draw
        menu.saw("agentkit · new", "Orchestrator [fable]: ")
        menu.saw("<lines True>")                # the question reads a line, echoed, as ever
        menu.send(b"q\n")
        menu.saw("<answered 'q'>")
        mark = len(menu.text())
        menu.frame(lambda lines: any("seat-a" in line for line in lines))
        menu.leave()
        self.assertNotIn("not a key", menu.text())
        self.assertEqual(menu.text().count("agentkit · new"), 1)
        self.assertNotIn("agentkit · new", menu.text()[mark:])

    def test_keys_typed_past_a_question_are_the_menus_again_after_it(self):
        """`n`, its answer and the menu's next key at once: the question takes only its line."""
        menu = Menu(self, ["seat-a"])
        menu.frame()
        menu.send(b"nq\nq")
        menu.saw("<answered 'q'>")
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])   # and that `q` leaves

    def test_down_and_enter_open_the_second_seat(self):
        menu = Menu(self, ["seat-a", "seat-b", "seat-c"])
        lines = menu.frame()
        self.assertIn("seat-a", menu.highlighted(lines))
        self.assertRegex(lines[-1], r"^  ↑↓ move   ⏎ open   n new   x stop   c config")
        menu.send(DOWN)
        menu.frame(lambda lines: "seat-b" in menu.highlighted(lines))
        menu.send(b"j")
        menu.frame(lambda lines: "seat-c" in menu.highlighted(lines))
        menu.send(b"k")
        menu.frame(lambda lines: "seat-b" in menu.highlighted(lines))
        menu.send(ENTER)
        menu.saw("<opened seat-b>")
        menu.leave()
        self.assertNotIn("<opened seat-a>", menu.text())

    def test_a_click_opens_the_seat_on_that_row_and_the_key_line_is_its_keys(self):
        menu = Menu(self, ["seat-a", "seat-b", "seat-c"])
        lines = menu.frame()
        row = next(number for number, line in enumerate(lines, 1) if "seat-c" in line)
        menu.send(f"\x1b[<0;12;{row}M".encode())       # the button down is half a click
        time.sleep(0.3)
        self.assertNotIn("<opened", menu.text())
        menu.send(f"\x1b[<0;12;{row}m".encode())       # and up, the click
        menu.saw("<opened seat-c>")
        # the seat opened keeps the highlight, the wheel moves it, and a click on `n new` is `n`
        mark = len(menu.text())
        menu.frame(lambda lines: "seat-c" in menu.highlighted(lines))
        menu.send(f"\x1b[<64;12;{row}M".encode())
        menu.frame(lambda lines: "seat-b" in menu.highlighted(lines))
        lines = menu.frame()
        keyline = len(lines)
        column = lines[-1].index("n new") + 1
        menu.click(column, keyline, held=0.1)
        menu.saw("agentkit · new", "Orchestrator [fable]: ", after=mark)
        menu.send(b"fable\n")                  # the answer is his, with none of the click in it
        menu.saw("<answered 'fable'>")
        self.assertNotIn("\x1b[<", menu.text()[mark:])
        lines = menu.frame(lambda lines: "seat-b" in menu.highlighted(lines))
        column = lines[-1].index("q leave") + 1
        menu.click(column, len(lines))
        self.assertEqual(menu.proc.wait(15), 0, menu.text()[-3000:])
        self.assertEqual(menu.text().count("<opened"), 1)

    def test_the_highlight_stays_on_its_seat_when_a_seat_above_it_goes(self):
        menu = Menu(self, ["seat-a", "seat-b", "seat-c"], tick=0.2)
        menu.frame()
        menu.send(DOWN)
        menu.frame(lambda lines: "seat-b" in menu.highlighted(lines))
        menu.set_seats(["seat-b", "seat-c"])       # seat-a stopped from somewhere else
        lines = menu.frame(lambda lines: not any("seat-a" in line for line in lines))
        highlighted = menu.highlighted(lines)
        self.assertIn("seat-b", highlighted)
        self.assertRegex(highlighted, r"^› 1  seat-b")   # its number moved; the highlight did not
        menu.send(ENTER)
        menu.saw("<opened seat-b>")
        menu.leave()

    def test_q_gives_the_terminal_back_exactly_as_it_was(self):
        menu = Menu(self, ["seat-a"])
        menu.frame()
        during = termios.tcgetattr(menu.slave)
        self.assertFalse(during[3] & termios.ICANON)
        self.assertFalse(during[3] & termios.ECHO)
        self.assertTrue(during[3] & termios.ISIG)          # ^C still interrupts
        menu.leave()
        self.assertEqual(termios.tcgetattr(menu.slave), menu.before)
        tail = menu.text().rsplit("\x1b[J", 1)[-1]
        for sequence in GIVEN:                             # clicks off, cursor on, screen back
            self.assertIn(sequence, tail)

    def test_a_signal_gives_the_terminal_back_before_it_ends_the_menu(self):
        menu = Menu(self, ["seat-a"])
        menu.frame()
        self.assertNotEqual(termios.tcgetattr(menu.slave), menu.before)
        menu.proc.send_signal(signal.SIGTERM)             # the child's own pid, nothing wider
        self.assertEqual(menu.proc.wait(15), -signal.SIGTERM)
        self.assertEqual(termios.tcgetattr(menu.slave), menu.before)
        self.assertIn("\x1b[?1049l", menu.text().rsplit("\x1b[J", 1)[-1])

    def test_a_second_digit_within_half_a_second_makes_two_and_no_key_is_dropped(self):
        menu = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)])
        menu.frame()
        menu.send(b"12")
        menu.saw("<opened seat-12>")
        menu.send(b"3")                     # no seat 30 to wait for: at once
        menu.saw("<opened seat-03>")
        began = time.monotonic()
        menu.send(b"1")                     # alone: seat 1, once half a second has passed
        menu.saw("<opened seat-01>")
        self.assertGreaterEqual(time.monotonic() - began, 0.45)
        mark = len(menu.text())
        menu.send(b"1n")                    # the key read while waiting is still pressed
        menu.saw("<opened seat-01>", "agentkit · new", after=mark)
        menu.send(b"q\n")
        menu.saw("<answered 'q'>", after=mark)
        menu.frame(lambda lines: "seat-01" in menu.highlighted(lines))
        menu.leave()
        self.assertNotIn("<opened seat-10>", menu.text())

    def test_a_resize_while_a_digit_waits_keeps_its_half_second(self):
        menu = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)])
        menu.frame()
        menu.send(b"1")
        time.sleep(0.1)
        menu.resize(30, 90)                     # the phone turned between the two digits
        time.sleep(0.1)
        menu.send(b"2")
        menu.saw("<opened seat-12>")
        menu.frame(lambda lines: len(lines[0]) == 90)     # and it still draws at the new size
        menu.leave()
        for seat in ("seat-01", "seat-02"):
            self.assertNotIn(f"<opened {seat}>", menu.text())

    def test_a_click_read_while_a_digit_waits_opens_what_was_under_it(self):
        """The click is read before the digit's seat opens, and kept with the page it was on."""
        menu = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)], rows=12, cols=40)
        menu.frame()
        menu.send(b"j" * 11)
        lines = menu.frame(lambda lines: "seat-12" in menu.highlighted(lines))
        self.assertFalse(any("seat-01" in line for line in lines), lines)   # another page is up
        row = next(number for number, line in enumerate(lines, 1) if "seat-12" in line)
        menu.send(b"1")
        menu.click(10, row)
        text = menu.saw("<opened seat-01>", "<opened seat-12>")
        self.assertLess(text.index("<opened seat-01>"), text.index("<opened seat-12>"))
        menu.frame(lambda lines: "seat-12" in menu.highlighted(lines))
        menu.leave()
        self.assertEqual(menu.text().count("<opened"), 2)

    def test_a_key_pressed_while_the_button_is_down_hands_on_none_of_the_click(self):
        """Down, a key, and up whenever: the key acts at once, and whatever reads next is handed
        all he typed after it and none of the click, however late the button comes up."""
        menu = Menu(self, ["seat-a", "seat-b", "seat-c"], session_reads=True)
        lines = menu.frame()
        row = next(number for number, line in enumerate(lines, 1) if "seat-b" in line)
        down, up = f"\x1b[<0;10;{row}M".encode(), f"\x1b[<0;10;{row}m".encode()
        menu.send(down + b"n")
        menu.saw("Orchestrator [fable]: ")
        time.sleep(0.3)                          # the button comes up long after the key
        menu.send(up + b"fable\n")
        menu.saw("<answered 'fable'>")
        # a whole answer typed before the button comes up is that answer, and the only one
        mark = len(menu.text())
        menu.frame(lambda lines: "seat-a" in menu.highlighted(lines), after=mark)
        menu.send(down + b"nfable\n" + up)
        menu.saw("<answered 'fable'>", after=mark)
        # a seat's session is handed what he typed after its number, and the menu none of it
        mark = len(menu.text())
        menu.frame(lambda lines: "seat-a" in menu.highlighted(lines), after=mark)
        menu.send(down + b"3hello\n" + up)
        menu.saw("<opened seat-c>", "<session read b'hello\\n'>", after=mark)
        menu.frame(lambda lines: "seat-c" in menu.highlighted(lines), after=mark)
        menu.leave()
        self.assertEqual(menu.text().count("<answered"), 2)
        self.assertEqual(menu.text().count("<opened"), 1)

    def test_a_button_down_in_the_digit_wait_keeps_its_half_second(self):
        menu = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)])
        lines = menu.frame()
        row = next(number for number, line in enumerate(lines, 1) if "seat-05" in line)
        menu.send(b"1")
        time.sleep(0.1)
        menu.send(f"\x1b[<0;10;{row}M".encode())       # the button goes down and stays down
        time.sleep(0.6)
        menu.send(b"2")                                  # past the half second: a key of its own
        text = menu.saw("<opened seat-01>", "<opened seat-02>")
        self.assertLess(text.index("<opened seat-01>"), text.index("<opened seat-02>"))
        menu.send(f"\x1b[<0;10;{row}m".encode())       # up long after the terminal changed hands
        time.sleep(0.3)
        menu.leave()
        self.assertEqual(menu.text().count("<opened"), 2)

    def test_a_pipe_still_reads_a_line_at_a_time(self):
        home = tempfile.TemporaryDirectory(prefix="menu-keys-")
        self.addCleanup(home.cleanup)
        seats = Path(home.name) / "seats.json"
        seats.write_text(json.dumps(["seat-a", "seat-b"]))
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "MENU_KEYS_REPO": str(REPO), "MENU_KEYS_SEATS": str(seats),
                    "MENU_KEYS_TICK": "10", "MENU_KEYS_SLOW": "0",
                    "MENU_KEYS_SESSION_READS": "0"})
        proc = subprocess.run([sys.executable, "-c", CHILD], input="zz\n\nn\nq\n2\nq\n",
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = proc.stdout
        self.assertIn("\n  n new   x stop   c config   i info   q leave\n", out)
        self.assertIn("not a key: 'zz'", out)
        self.assertIn("<lines None>", out)
        self.assertIn("<answered 'q'>", out)
        self.assertIn("<opened seat-b>", out)
        for taken in ("\x1b[?1049h", "\x1b[?1000h", "›", "↑↓ move"):
            self.assertNotIn(taken, out)

    def test_the_list_selector_picks_one_or_several_and_esc_goes_back(self):
        Key = terminal.Key

        def pick(keys, *args, **kwargs):
            with patch.object(terminal, "read_key", side_effect=keys), \
                    patch.object(terminal, "width", return_value=40), \
                    redirect_stdout(io.StringIO()) as out:
                return terminal.choose(*args, **kwargs), out.getvalue()

        choices = ["fable", "opus", "astra"]
        chosen, out = pick([Key("down"), Key("enter")], choices, default="opus")
        self.assertEqual(chosen, "astra")
        self.assertIn("\x1b[3A", out)                     # drawn over in place, not below
        self.assertEqual(pick([Key("char", "k"), Key("wheel-up"), Key("enter")], choices,
                              default="astra")[0], "fable")
        self.assertEqual(pick([Key("space"), Key("char", "j"), Key("space"), Key("enter")],
                              choices, default=["astra"], several=True)[0],
                         ["fable", "opus", "astra"])
        self.assertEqual(pick([Key("space"), Key("enter")], choices, default=["fable"],
                              several=True)[0], [])
        self.assertIsNone(pick([Key("down"), Key("esc")], choices)[0])
        self.assertIsNone(pick([Key("char", "q")], choices)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)

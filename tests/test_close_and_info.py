"""`x` acts on the highlighted seat, and a done one closes with that one key; a press begun on
one screen is no click on the next; a seat stopped twice leaves no rulebook and no open card.

The menu tests run `menu.loop` in a child process on a pty of its own, the way
tests/test_menu_keys.py does, with the seat listing, each seat's word, the usage rows and the
probe faked, and the stop `x` starts reduced to a process of its own that says on the menu's
terminal which seat it was handed and takes it off the listing; the past screen's `x` waits on
that same process.  The stop
tests call the real `orch.cmd_stop` in a throwaway HOME with tmux faked and no runs to stop.
Nothing here starts a seat or a tmux server, and the only process signalled is the test's own
child.
"""

from contextlib import contextmanager, redirect_stdout
import fcntl
import io
import itertools
import json
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
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import browser, config, menu, notify, orch, statusbar, terminal, watch

# The child: the real loop, draw, key reader and selector; fakes for what a seat is and the stop.
CHILD = r"""
import json, os, subprocess, sys
sys.path.insert(0, os.environ["CLOSE_REPO"])
from pathlib import Path
from agentkit import config, menu, orch

SEATS = Path(os.environ["CLOSE_SEATS"])        # {name: word}, in the listing's order
STOPPED = "stopped"      # a seat the owner stopped: an `idle` row with `closed` set on it
seats = lambda: json.loads(SEATS.read_text())
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0,
     "closed": 1 if word == STOPPED else None} for name, word in seats().items()]
menu.seat_row_state = lambda cfg, session, **facts: {
    "word": seats().get(session["name"], "working").replace(STOPPED, "idle"),
    "reason": "", "since": None}
menu.usage_lines = lambda cfg, width, **_kw: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
# The stop, in a process of its own as `menu.teardown`'s is: once CLOSE_HOLD is gone, if set,
# it takes the seat off the listing and names it on the menu's terminal, or refuses as
# `close_seat` does with CLOSE_REFUSE -- and, first, as `orch.cmd_stop` does where the
# environment it was handed makes it another seat's stop (`config.check_stop_owner`).
STOP = r'''
import json, os, sys, time
from pathlib import Path
from agentkit import config
name = sys.argv[1]
while os.path.exists(os.environ.get("CLOSE_HOLD") or ""):
    time.sleep(0.01)
try:
    config.check_stop_owner(name)
except config.Error as exc:
    sys.exit(f"stop: {exc}")
if os.environ.get("CLOSE_REFUSE"):
    from agentkit import orch
    sys.exit(orch.leave_notice(f"stop: {name} refused"))
seats = Path(os.environ["CLOSE_SEATS"])
left = json.loads(seats.read_text())
left.pop(name, None)
seats.write_text(json.dumps(left))
os.write(os.open(os.environ["CLOSE_TTY"], os.O_WRONLY | os.O_NOCTTY), f"<stopped {name}>".encode())
'''
menu.teardown = lambda name, dry_run: [sys.executable, "-c", STOP, name]
menu.close_seat = lambda name, dry_run, **_kw: subprocess.run(
    menu.teardown(name, dry_run), cwd=os.environ["CLOSE_REPO"])
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>", flush=True)
sys.exit(menu.loop(config.load(), overlay=os.environ.get("CLOSE_OVERLAY") == "1"))
"""
ESC, DOWN, ENTER = b"\x1b", b"\x1b[B", b"\r"
stop_means = menu.stop_means     # the tests below name their pty menu `menu`
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


class Menu:
    """One child menu on a pty: what it wrote so far, and keys sent to it."""

    def __init__(self, case, seats, rows=30, cols=100, own=None, hold=None, refuse=False):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="close-info-")
        case.addCleanup(home.cleanup)
        self.seats = Path(home.name) / "seats.json"
        self.seats.write_text(json.dumps(seats))
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "CLOSE_REPO": str(REPO), "CLOSE_SEATS": str(self.seats),
                    "CLOSE_TTY": os.ttyname(self.slave), "CLOSE_HOLD": str(hold or ""),
                    "CLOSE_REFUSE": "1" if refuse else ""})
        if own:
            env.update({"CLOSE_OVERLAY": "1", "AGENTKIT_SESSION": own})
        self.leave_key = "esc leave"
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

    def text(self):
        with self.lock:
            return self.output.decode("utf-8", "replace")

    def until(self, ready, what, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            found = ready(self.text())
            if found:
                return found
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {what}:\n{self.text()[-3000:]!r}")
            time.sleep(0.02)

    def saw(self, *texts, after=0):
        return self.until(lambda text: all(t in text[after:] for t in texts) and text,
                          " & ".join(texts))

    def send(self, keys):
        os.write(self.master, keys)

    def mark(self):
        return len(self.text())

    def frame(self, where=None, keys=None, after=0):
        """The lines of the last whole screen written over in place whose key line says `keys`
        (the menu's own by default), as the screen shows them; row 1 first."""
        keys = keys or self.leave_key

        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if any(keys in line for line in lines):
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, f"a screen ending {keys!r}")

    def choices(self, after=0):
        """(the row the selector drew its first answer on, its two lines as shown)."""
        def ready(text):
            found = re.search(r"\x1b\[(\d+);1H\r(.*?)\x1b\[K\r?\n\r(.*?)\x1b\[K", text[after:])
            if not found:
                return None
            return int(found.group(1)), [terminal.ANSI.sub("", found.group(n)) for n in (2, 3)]
        return self.until(ready, "the stop question's answers")

    def highlighted(self, lines):
        marked = [line for line in lines if line.startswith("›")]
        self.case.assertEqual(len(marked), 1, lines)
        return marked[0]

    def click(self, col, row):
        """The left button down and up at `col`, `row`, as a terminal in mode 1006 reports it."""
        self.send(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode())

    def resize(self, rows, cols):
        """What a terminal that turns does: a new size, then SIGWINCH to the child alone."""
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)

    def leave(self):
        self.send(ESC)
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


class CloseAndInfo(unittest.TestCase):
    def test_x_on_a_done_seat_closes_it_without_a_question(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"})
        menu.frame()
        menu.send(b"j")
        lines = menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        self.assertRegex(lines[-1], r"   x close   ")
        mark = menu.mark()
        menu.send(b"x")
        menu.saw("<stopped omega>", after=mark)
        lines = menu.frame(lambda lines: not any("omega" in line for line in lines), after=mark)
        self.assertIn("alpha", menu.highlighted(lines))
        menu.leave()
        self.assertNotIn("everything it runs", menu.text())
        self.assertEqual(menu.text().count("<stopped"), 1)

    def test_the_popup_over_a_seat_stops_another_and_removes_a_past_one(self):
        """x is the owner's in Ctrl-b m too: the seat it is over stops no other seat's work,
        but the person at its keys does."""
        menu = Menu(self, {"alpha": "working", "omega": "done", "atoll": "stopped"}, own="alpha")
        menu.frame()
        menu.send(b"j")
        menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        menu.saw("<stopped omega>", after=mark)
        menu.frame(lambda lines: not any("omega" in line for line in lines), after=mark)
        mark = menu.mark()
        menu.send(b"p")
        menu.frame(lambda lines: "atoll" in menu.highlighted(lines), after=mark, keys="esc back")
        menu.send(b"x")
        menu.saw("<stopped atoll>", after=mark)
        menu.send(ESC)
        menu.frame(after=menu.mark())
        menu.leave()
        self.assertNotIn("owned by seat", menu.text())

    def test_x_on_a_working_seat_asks_under_its_row_and_esc_keeps(self):
        menu = Menu(self, {"beta": "needs you", "alpha": "working", "omega": "done"})
        lines = menu.frame()
        self.assertIn("beta", menu.highlighted(lines))      # the first seat, where it starts
        mark = menu.mark()
        menu.send(b"x")
        asked = menu.frame(keys="esc back", after=mark)
        row = next(number for number, line in enumerate(asked, 1) if "beta" in line)
        self.assertEqual(asked[row:row + 2], ["", "  Stop beta and everything it runs?"])
        means = list(itertools.takewhile(lambda line: line.strip(), asked[row + 2:]))
        self.assertEqual(" ".join(line.strip() for line in means), stop_means(0))
        self.assertFalse(any(line.startswith("›") for line in asked), asked)
        top, answers = menu.choices(after=mark)
        self.assertEqual(top, row + 3 + len(means))         # the two lines under what it means
        self.assertEqual(answers, ["› ✓ Keep", "  ✗ Stop"])  # Keep is where the highlight starts
        self.assertEqual(asked[top - 1:top + 2], ["", "", ""])
        self.assertEqual(asked[-1].strip(), "esc back")
        mark = menu.mark()
        menu.send(ESC)
        lines = menu.frame(after=mark)
        self.assertIn("beta", menu.highlighted(lines))
        menu.send(b"x")
        menu.frame(keys="esc back", after=mark)
        mark = menu.mark()
        menu.send(ENTER)                                    # Enter on Keep keeps it as well
        menu.frame(after=mark)
        menu.leave()
        self.assertNotIn("<stopped", menu.text())

    def test_enter_on_stop_stops_and_a_click_on_stop_does_too(self):
        menu = Menu(self, {"alpha": "working", "beta": "working", "omega": "done"})
        menu.frame()
        mark = menu.mark()
        menu.send(b"x")
        menu.choices(after=mark)
        moved = menu.mark()
        menu.send(DOWN)
        self.assertEqual(menu.choices(after=moved)[1], ["  ✓ Keep", "› ✗ Stop"])
        menu.send(ENTER)
        menu.saw("<stopped alpha>", after=mark)
        lines = menu.frame(lambda lines: not any("alpha" in line for line in lines),
                           after=mark)
        self.assertIn("beta", menu.highlighted(lines))
        mark = menu.mark()
        menu.send(b"x")
        top, _ = menu.choices(after=mark)
        menu.click(4, top + 1)                              # on `Stop`, one row under `Keep`
        menu.saw("<stopped beta>", after=mark)
        menu.frame(lambda lines: not any("beta" in line for line in lines), after=mark)
        menu.leave()
        self.assertEqual(menu.text().count("<stopped"), 2)

    def test_the_key_line_word_follows_the_highlight(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"})
        lines = menu.frame()
        self.assertIn("   x stop   ", lines[-1])
        self.assertNotIn("x close", lines[-1])
        menu.send(b"j")
        lines = menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        self.assertIn("   x close   ", lines[-1])
        menu.send(b"k")
        lines = menu.frame(lambda lines: "alpha" in menu.highlighted(lines))
        self.assertIn("   x stop   ", lines[-1])
        menu.leave()

    def test_a_press_begun_on_another_screen_answers_nothing_on_this_one(self):
        """The button down on one screen and up on the next is no click: not on `Stop` under
        the question, not on a seat once the question is gone, not on `esc back` of `c`."""
        menu = Menu(self, {"alpha": "working", "beta": "working"})
        lines = menu.frame()
        seat = next(number for number, line in enumerate(lines, 1) if "beta" in line)
        mark = menu.mark()
        menu.send(f"\x1b[<0;4;{seat}M".encode() + b"x")      # down on the menu, then `x`
        top, _ = menu.choices(after=mark)
        mark = menu.mark()
        menu.send(f"\x1b[<0;4;{top + 1}m".encode() + ESC)    # up on `Stop`: no answer; Esc keeps
        menu.frame(after=mark)
        mark = menu.mark()
        menu.send(b"x")
        top, _ = menu.choices(after=mark)
        mark = menu.mark()
        menu.send(f"\x1b[<0;4;{top}M".encode() + ESC)        # down on `Keep`, and Esc
        menu.frame(after=mark)
        mark = menu.mark()
        menu.send(f"\x1b[<0;4;{seat}m".encode() + b"c")      # up on beta's row: nothing opens
        config = menu.frame(keys="esc back", after=mark)
        mark = menu.mark()
        column = config[-1].index("esc back") + 3
        menu.send(f"\x1b[<0;{column};5M".encode() + ESC)      # down on the config screen, Esc
        menu.frame(after=mark)
        mark = menu.mark()
        menu.send(b"c")
        config = menu.frame(keys="esc back", after=mark)
        mark = menu.mark()
        menu.send(f"\x1b[<0;{column};{len(config)}m".encode() + ESC)  # up on `esc back`: nothing
        menu.frame(after=mark)                    # the Esc was the config screen's, not the menu's
        menu.leave()
        self.assertNotIn("<stopped", menu.text())
        self.assertNotIn("<opened", menu.text())

    def test_a_resize_draws_the_question_and_its_answers_where_they_now_are(self):
        long = "a-rather-long-seat-name-for-the-phone"
        menu = Menu(self, {long: "working", "omega": "working"})
        menu.frame()
        mark = menu.mark()
        menu.send(b"x")
        before, _ = menu.choices(after=mark)
        mark = menu.mark()
        menu.resize(24, 40)                       # the question now wraps onto three lines,
                                                  # and what it means onto two
        asked = menu.frame(lambda lines: len(lines[0]) == 40, keys="esc back", after=mark)
        top, answers = menu.choices(after=mark)
        self.assertGreater(top, before)
        at = asked.index("  and everything it runs?")
        self.assertEqual(asked[at - 2:at + 1], ["  Stop", f"  {long}", "  and everything it runs?"])
        means = list(itertools.takewhile(lambda line: line.strip(), asked[at + 1:]))
        self.assertEqual(" ".join(line.strip() for line in means), stop_means(0))
        self.assertGreater(len(means), 1)                  # what it means wraps onto more lines
        self.assertEqual(top, at + 2 + len(means))
        self.assertEqual(answers, ["› ✓ Keep", "  ✗ Stop"])
        for line in asked:
            self.assertLessEqual(terminal.cells(line), 40, line)
        menu.click(4, top + 1)                    # `Stop`, where it is drawn now
        menu.saw(f"<stopped {long}>", after=mark)
        menu.frame(lambda lines: not any(long in line for line in lines), after=mark)
        menu.leave()


class ClosedSeat(Sandbox):
    """The real `orch.cmd_stop`, in a throwaway HOME, with tmux and Discord faked."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "",
            "AGENTKIT_DISCORD_WEBHOOK": "https://discord.invalid/api/webhooks/1/token"}))
        for name in INHERITED[:7]:
            os.environ.pop(name, None)            # the Sandbox's own patch puts them back
        self.tmux = []
        self.stack.enter_context(patch.object(
            orch, "tmux_out", side_effect=lambda *args, **kw: self.tmux.append(args) or (0, "")))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(browser, "close_tab"))
        self.edits, self.held = [], False
        self.stack.enter_context(patch.object(notify.urllib.request, "urlopen",
                                              side_effect=self.discord))
        self.stack.enter_context(patch.object(watch, "state_lock",
                                              lambda real=watch.state_lock: self.lock(real)))
        config.save_session(self.cfg, "atoll", self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"],
                            {"cwd": str(self.root), "created": time.time()})

    def discord(self, request, timeout=None):
        self.assertFalse(self.held, "the edit went out under the state lock")
        self.edits.append((request.get_method(), request.full_url, json.loads(request.data)))
        return io.BytesIO(b"{}")

    @contextmanager
    def lock(self, real):
        with real():
            self.held = True
            try:
                yield
            finally:
                self.held = False

    def stop(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop(["atoll"]), 0)

    def test_a_closed_seat_leaves_no_rulebook(self):
        mine = [config.STATE / "rulebook-atoll.md"]
        kept = [config.STATE / "rulebook-atoll-fix.md"]
        for path in mine + kept:
            path.write_text("{}\n")
        self.stop()                                 # stopped: kept, for its number to reopen it
        for path in mine + kept:
            self.assertTrue(path.exists(), path)
        self.stop()                                 # stopped again: gone
        for path in mine:
            self.assertFalse(path.exists(), path)
        for path in kept:
            self.assertTrue(path.exists(), path)
        self.assertEqual(self.tmux, [])            # no tmux session by the name: nothing killed

    def test_a_renamed_seat_leaves_nothing_under_the_name_it_was_launched_with(self):
        left = [config.STATE / "rulebook-atoll.md", config.STATE / "stop-atoll.json"]
        for path in left:
            path.write_text("{}\n")
        config.rename_session("atoll", "beta")    # what a rename moves, and what it leaves
        self.assertTrue(all(path.exists() for path in left))
        for _ in ("stopped", "removed"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(orch.cmd_stop(["beta"]), 0)
        for path in left + [config.session_path("atoll"), config.session_path("beta")]:
            self.assertFalse(path.exists(), path)

    def test_a_rename_carries_every_seat_file_but_the_rulebook_and_the_turn_latch(self):
        kinds = config.SEAT_FILES.keys() - {"session"}
        for kind in kinds:
            config.seat_file(kind, "atoll").write_text("{}\n")
        config.rename_session("atoll", "beta")
        for kind in kinds - {"rulebook", "stop", "launch"}:
            self.assertFalse(config.seat_file(kind, "atoll").exists(), kind)
            self.assertTrue(config.seat_file(kind, "beta").exists(), kind)
        self.assertTrue(config.rulebook_path("atoll").exists())   # its orchestrator still reads it
        self.assertTrue(config.stop_path("atoll").exists())       # its hooks still write it
        self.assertTrue(config.seat_file("launch", "atoll").exists())   # a starting pane reads it

    def test_a_stopped_seats_card_goes_and_what_went_out_stays_as_it_went(self):
        config.card_path("atoll").write_text(json.dumps({
            "word": "needs you", "since": 100, "episode": "e1", "sent": True}) + "\n")
        self.stop()
        self.assertEqual(self.edits, [])
        self.assertFalse(config.card_path("atoll").exists())
        self.assertTrue(config.session_path("atoll").exists())    # kept a week, card or no card

    def test_every_seats_bar_offers_the_menu(self):
        def key(word, last=""):
            return statusbar.lines("atoll", "fable", word, last)[2].replace(
                "#[fg=#6c7086]", "").replace("#[default]", "")
        for word in (None, "working", "needs you", "done"):
            self.assertEqual(key(word), "Ctrl-b m  menu ")


if __name__ == "__main__":
    unittest.main(verbosity=2)

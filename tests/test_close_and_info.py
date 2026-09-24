"""`x` acts on the highlighted seat and a done one closes with that one key; `i` is one calm screen
read with the keys; a stopped seat leaves no rulebook, no idle-compact stamp and no open card.

The menu tests run `menu.loop` in a child process on a pty of its own, the way
tests/test_menu_keys.py does, with the seat listing, each seat's word, the usage rows and the
probe faked, and `orch.cmd_stop` reduced to a line saying which seat it was handed.  The stop
tests call the real `orch.cmd_stop` in a throwaway HOME with tmux faked and no runs to stop.
Nothing here starts a seat or a tmux server, and the only process signalled is the test's own
child.
"""

from contextlib import contextmanager, redirect_stdout
import fcntl
import hashlib
import io
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
from test_v4n import Sandbox
from agentkit import browser, config, menu, notify, orch, terminal, watch

# The child: the real loop, draw, key reader and selector; fakes for what a seat is and the stop.
CHILD = r"""
import json, os, sys
sys.path.insert(0, os.environ["CLOSE_REPO"])
from pathlib import Path
from agentkit import config, menu, orch

SEATS = Path(os.environ["CLOSE_SEATS"])        # {name: word}, in the listing's order
seats = lambda: json.loads(SEATS.read_text())
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0} for name in seats()]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {
    "word": seats().get(session["name"], "working"), "reason": "", "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
menu.installed = lambda refresh=False: "abc1234 · 23 Sep"
menu.stop_session_runs = lambda name, dry_run=False: None

def cmd_stop(argv):
    print(f"<stopped {argv[0]}>", flush=True)
    left = seats()
    left.pop(argv[0], None)
    SEATS.write_text(json.dumps(left))
    return 0

orch.cmd_stop = cmd_stop
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>", flush=True)
sys.exit(menu.loop(config.load(), overlay=os.environ.get("CLOSE_OVERLAY") == "1"))
"""
ESC, DOWN, ENTER = b"\x1b", b"\x1b[B", b"\r"
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


class Menu:
    """One child menu on a pty: what it wrote so far, and keys sent to it."""

    def __init__(self, case, seats, rows=30, cols=100, own=None):
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
                    "CLOSE_REPO": str(REPO), "CLOSE_SEATS": str(self.seats)})
        if own:
            env.update({"CLOSE_OVERLAY": "1", "AGENTKIT_SESSION": own})
        self.leave_key = "q close" if own else "q leave"
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
        self.send(b"q")
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

    def test_x_on_a_working_seat_asks_under_its_row_and_esc_keeps(self):
        menu = Menu(self, {"alpha": "working", "beta": "needs you", "omega": "done"})
        lines = menu.frame()
        self.assertIn("beta", menu.highlighted(lines))      # needs you sorts first
        mark = menu.mark()
        menu.send(b"x")
        asked = menu.frame(keys="esc keep", after=mark)
        row = next(number for number, line in enumerate(asked, 1) if "beta" in line)
        self.assertEqual(asked[row], "  Stop beta and everything it runs?")
        self.assertFalse(any(line.startswith("›") for line in asked), asked)
        top, answers = menu.choices(after=mark)
        self.assertEqual(top, row + 2)                      # the two lines under the question
        self.assertEqual(answers, ["› Keep", "  Stop"])     # Keep is where the highlight starts
        self.assertEqual(asked[top - 1:top + 1], ["", ""])
        self.assertEqual(asked[-1].strip(), "esc keep")
        mark = menu.mark()
        menu.send(ESC)
        lines = menu.frame(after=mark)
        self.assertIn("beta", menu.highlighted(lines))
        menu.send(b"x")
        menu.frame(keys="esc keep", after=mark)
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
        self.assertEqual(menu.choices(after=moved)[1], ["  Keep", "› Stop"])
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

    def test_info_is_one_screen_read_with_the_keys_and_esc_returns(self):
        menu = Menu(self, {"alpha": "working"})
        menu.frame()
        mark = menu.mark()
        menu.send(b"i")
        info = menu.frame(keys="esc back", after=mark)
        self.assertTrue(info[0].startswith("agentkit · info"), info)
        body = "\n".join(info)
        self.assertIn("agentkit: you talk to one orchestrator", body)
        for line in (*menu_module_lines(), "agentkit abc1234 · 23 Sep"):
            self.assertIn(line, body)
        for gone in ("results:", "usage left", "q back"):
            self.assertNotIn(gone, body)
        self.assertEqual(info[-1], "  esc back")
        time.sleep(0.3)                           # a line typed here would be read; none is
        self.assertNotIn("\x1b[?1049l", menu.text()[mark:])   # the menu's screen, still taken
        mark = menu.mark()
        menu.send(ESC)
        menu.frame(after=mark)
        mark = menu.mark()
        menu.send(b"i")
        menu.frame(keys="esc back", after=mark)
        menu.send(b"q")                           # `q` goes back, and does not leave the menu
        menu.frame(after=mark)
        menu.leave()
        self.assertNotIn("<opened", menu.text())

    def test_info_scrolls_where_it_does_not_fit_and_a_click_on_esc_back_returns(self):
        menu = Menu(self, {"alpha": "working"}, rows=12, cols=40)
        menu.frame()
        mark = menu.mark()
        menu.send(b"i")
        info = menu.frame(keys="esc back", after=mark)
        self.assertLessEqual(len(info), 12)
        self.assertEqual(info[-1], "  ↑↓ scroll   esc back")
        self.assertTrue(info[2].startswith("agentkit: you talk"), info)
        for line in info:
            self.assertLessEqual(terminal.cells(line), 40, line)
        mark = menu.mark()
        menu.send(DOWN + DOWN)
        info = menu.frame(lambda lines: not lines[2].startswith("agentkit: you"),
                          keys="esc back", after=mark)
        self.assertEqual(info[-1], "  ↑↓ scroll   esc back")
        mark = menu.mark()
        menu.send(b"\x1b[<65;5;5M" * 40)          # the wheel, down past the end: it stops there
        info = menu.frame(lambda lines: "agentkit abc1234" in "\n".join(lines),
                          keys="esc back", after=mark)
        mark = menu.mark()
        menu.click(info[-1].index("esc back") + 3, len(info))
        menu.frame(after=mark)
        menu.leave()

    def test_the_popup_closes_its_own_done_seat_and_asks_under_its_own_row(self):
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="omega")
        lines = menu.frame()
        self.assertIn("alpha", menu.highlighted(lines))
        self.assertIn("x close this session", "\n".join(lines))
        mark = menu.mark()
        menu.send(b"x")                           # its own seat, wherever the highlight is
        menu.saw("<stopped omega>", after=mark)
        menu.leave()
        menu = Menu(self, {"alpha": "working", "omega": "done"}, own="alpha")
        menu.frame()
        menu.send(b"j")
        lines = menu.frame(lambda lines: "omega" in menu.highlighted(lines))
        self.assertIn("x stop this session", "\n".join(lines))
        mark = menu.mark()
        menu.send(b"x")
        asked = menu.frame(keys="esc keep", after=mark)
        row = next(number for number, line in enumerate(asked, 1) if "alpha" in line)
        self.assertEqual(asked[row], "  Stop alpha and everything it runs?")
        mark = menu.mark()
        menu.send(ESC)
        menu.frame(after=mark)
        menu.leave()
        self.assertNotIn("<stopped", menu.text())


    def test_a_press_begun_on_another_screen_answers_nothing_on_this_one(self):
        """The button down on one screen and up on the next is no click: not on `Stop` under
        the question, not on a seat once the question is gone, not on `esc back`."""
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
        menu.send(f"\x1b[<0;4;{seat}m".encode() + b"i")      # up on beta's row: nothing opens
        info = menu.frame(keys="esc back", after=mark)
        mark = menu.mark()
        column = info[-1].index("esc back") + 3
        menu.send(f"\x1b[<0;{column};5M".encode() + ESC)      # down on the info screen, Esc
        menu.frame(after=mark)
        mark = menu.mark()
        menu.send(b"i")
        info = menu.frame(keys="esc back", after=mark)
        mark = menu.mark()
        menu.send(f"\x1b[<0;{column};{len(info)}m".encode() + ESC)   # up on `esc back`: nothing
        menu.frame(after=mark)                    # the Esc was the info screen's, not the menu's
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
        menu.resize(24, 40)                       # the question now wraps onto three lines
        asked = menu.frame(lambda lines: len(lines[0]) == 40, keys="esc keep", after=mark)
        top, answers = menu.choices(after=mark)
        self.assertGreater(top, before)
        self.assertEqual(asked[top - 4:top - 1], ["  Stop", f"  {long}", "  and everything it runs?"])
        self.assertEqual(answers, ["› Keep", "  Stop"])
        for line in asked:
            self.assertLessEqual(terminal.cells(line), 40, line)
        menu.click(4, top + 1)                    # `Stop`, where it is drawn now
        menu.saw(f"<stopped {long}>", after=mark)
        menu.frame(lambda lines: not any(long in line for line in lines), after=mark)
        menu.leave()

    def test_a_resize_wraps_the_info_screen_anew(self):
        menu = Menu(self, {"alpha": "working"}, rows=30, cols=100)
        menu.frame()
        mark = menu.mark()
        menu.send(b"i")
        info = menu.frame(keys="esc back", after=mark)
        self.assertEqual(info[2], "agentkit: you talk to one orchestrator; it works until it is "
                                  "done or it needs you.")
        mark = menu.mark()
        menu.resize(24, 40)
        info = menu.frame(lambda lines: len(lines[0]) == 40, keys="esc back", after=mark)
        self.assertLessEqual(len(info), 24)
        self.assertEqual(info[2], "agentkit: you talk to one orchestrator;")
        self.assertEqual(info[-1], "  ↑↓ scroll   esc back")
        for line in info:
            self.assertLessEqual(terminal.cells(line), 40, line)
        mark = menu.mark()
        menu.click(info[-1].index("esc back") + 3, len(info))
        menu.frame(after=mark)
        menu.leave()


def menu_module_lines():
    """The `i` screen's state and key lines, as the README prints them."""
    with patch.dict(os.environ, {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}):
        return [*menu.info_states(), *menu.INFO_KEYS]


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

    def test_a_closed_seat_leaves_no_rulebook_or_idle_compact_file(self):
        stamps = config.STATE / "idle-compact"
        stamps.mkdir()
        mine = [config.STATE / "rulebook-atoll.md", stamps / "atoll-4242.json",
                stamps / "atoll-4243.json"]
        kept = [config.STATE / "rulebook-atoll-fix.md", stamps / "atoll-fix-4244.json",
                stamps / "4245.json", stamps / "log"]
        for path in mine + kept:
            path.write_text("{}\n")
        self.stop()
        for path in mine:
            self.assertFalse(path.exists(), path)
        for path in kept:
            self.assertTrue(path.exists(), path)
        self.assertEqual(self.tmux, [])            # no tmux session by the name: nothing killed

    def test_a_renamed_seat_leaves_nothing_under_the_name_it_was_launched_with(self):
        stamps = config.STATE / "idle-compact"
        stamps.mkdir()
        left = [config.STATE / "rulebook-atoll.md", stamps / "atoll-4242.json"]
        for path in left:
            path.write_text("{}\n")
        config.rename_session("atoll", "beta")    # what a rename moves, and what it leaves
        self.assertTrue(all(path.exists() for path in left))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop(["beta"]), 0)
        for path in left + [config.session_path("atoll"), config.session_path("beta")]:
            self.assertFalse(path.exists(), path)

    def test_idle_compact_names_its_stamp_for_its_seat(self):
        told = self.root / "told"
        env = {key: value for key, value in os.environ.items() if key != "IDLE_COMPACT_STATE"}
        env.update({"HOME": str(self.root), "AGENTKIT_SESSION": "atoll", "TOLD": str(told)})
        subprocess.run([sys.executable, str(REPO / "tools/idle-compact.py"), "--",
                        "sh", "-c", 'printf %s "$IDLE_COMPACT_STATE" >"$TOLD"'],
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        self.assertRegex(told.read_text(), r"/\.agentkit/state/idle-compact/atoll-\d+\.json$")
        # and the daily collector still reads the pid off a stamp named either way
        from agentkit import run
        self.assertEqual(run.compact_pid(Path("atoll.v2-4242.json")), "4242")
        self.assertEqual(run.compact_pid(Path("4242.json")), "4242")

    def card(self):
        url = os.environ["AGENTKIT_DISCORD_WEBHOOK"]
        pending = {"message_id": "4242", "webhook": hashlib.sha256(url.encode()).hexdigest(),
                   "embed": {"title": "Needs you · atoll", "color": 16753920,
                             "fields": [{"name": "open", "value": "press 1"}]}}
        config.card_path("atoll").write_text(json.dumps({
            "word": "needs you", "since": 100, "episode": "e1", "sent": True,
            "open_needs": [pending]}) + "\n")

    def test_a_stopped_seats_open_card_reads_answered(self):
        self.card()
        self.stop()
        self.assertEqual(len(self.edits), 1, self.edits)
        method, url, body = self.edits[0]
        self.assertEqual((method, url), ("PATCH", os.environ["AGENTKIT_DISCORD_WEBHOOK"]
                                         + "/messages/4242"))
        self.assertEqual(body["embeds"][0]["title"], "Answered · atoll")
        self.assertNotIn("fields", body["embeds"][0])
        self.assertFalse(config.card_path("atoll").exists())

    def test_a_card_discord_would_not_edit_stays_for_the_tick(self):
        self.card()
        self.stack.enter_context(patch.object(notify.urllib.request, "urlopen",
                                              side_effect=OSError("down")))
        self.stop()
        card = json.loads(config.card_path("atoll").read_text())
        self.assertEqual(card["word"], "")
        self.assertEqual(len(card["open_needs"]), 1)
        self.assertFalse(config.session_path("atoll").exists())

    def test_a_done_seats_bar_offers_the_close(self):
        self.assertEqual(orch.bar("atoll", "fable", "done", "shipped")[1], " Ctrl-b m  x close ")
        for word in (None, "working", "needs you"):
            self.assertEqual(orch.bar("atoll", "fable", word)[1], " Ctrl-b m  menu ")


if __name__ == "__main__":
    unittest.main(verbosity=2)

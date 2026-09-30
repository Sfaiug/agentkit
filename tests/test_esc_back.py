"""Esc, and only Esc, goes back: from every screen the menu opens, from each question and each
text prompt, within 100 ms; on the main screen it leaves.  `q` goes back nowhere, and at a
prompt it is a letter.  Every key line drawn names `esc`.

The screen tests run `menu.loop` in a child process on a pty of its own, the way
tests/test_close_and_info.py does, with the seat listing, each seat's word, the usage rows, the
probe, the stop and the rename faked; each screen says when it returned, on the monotonic clock
the test reads too, so the time is Esc's own and no draw's.  The line-mode test drives
`menu.loop` in-process with `menu.wait_key` and `menu.read` mocked (AGENTS.md).  Nothing here
starts a seat or a tmux server, and the only process signalled is the test's own child.
"""

from contextlib import redirect_stdout
import fcntl
import io
import json
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
sys.path.insert(0, str(REPO / "tests"))
from test_v4n import Sandbox
from agentkit import menu, orch, terminal

# The child: the real loop, screens, fields and key reader; fakes for the seats and what acts.
CHILD = r"""
import os, sys, time
sys.path.insert(0, os.environ["ESC_REPO"])
from agentkit import config, menu, orch, terminal, usage

cfg = config.load()
config.save_session(cfg, "alpha", "opus", ["opus", "astra"], {"cwd": "/", "created": 0})
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0} for name in ("alpha", "omega")]
notices = [os.environ["ESC_NOTICE"]] if os.environ.get("ESC_NOTICE") else []
orch.job_notices = lambda: [notices.pop()] if notices else []
orch.taken_names = lambda: {"alpha", "omega"}
orch.rename = lambda old, new: print(f"<renamed {new}>", flush=True) or new
orch.cmd_stop = lambda argv: print(f"<stopped {argv[0]}>", flush=True)
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "",
                                                     "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: usage.Readings({})
menu.stop_session_runs = lambda name, dry_run=False: None
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>", flush=True)

def timed(module, name):
    real = getattr(module, name)

    def screen(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        finally:
            print(f"<back {name} {time.monotonic():.4f}>", flush=True)
    setattr(module, name, screen)

for module, name in ((menu, "config_matrix"), (menu, "config_model"), (menu, "config_add"),
                     (menu, "config_add_provider"), (menu, "config_remove_provider"),
                     (menu, "config_discord"),
                     (menu, "show_info"), (menu, "show_features"), (menu, "new_session"),
                     (menu, "rename_this_session"), (menu, "pause"), (terminal, "choose")):
    timed(module, name)
code = menu.loop(cfg, overlay=os.environ.get("ESC_OVERLAY") == "1")
print(f"<back loop {time.monotonic():.4f}>", flush=True)
sys.exit(code)
"""
# ACME's features command: one switch, listed.
FEATURES = r"""
import json
print(json.dumps([{"id": "dark", "name": "Dark mode", "you": False, "everyone": False,
                   "you_switchable": True}]))
"""
ESC, UP, DOWN, LEFT, RIGHT, ENTER = b"\x1b", b"\x1b[A", b"\x1b[B", b"\x1b[D", b"\x1b[C", b"\r"
ESC_WAIT = 0.1       # what Esc may take to go back
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


def title(name):
    """A screen whose top line is `agentkit · <name>` and the clock, and nothing between."""
    return lambda lines: bool(lines) and re.fullmatch(rf"agentkit · {re.escape(name)} +\d\d:\d\d",
                                                       lines[0])


class Menu:
    """One child menu on a pty over a HOME with ~/code/ACME: what it wrote, keys sent to it."""

    def __init__(self, case, own=None, notice=""):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="esc-back-")
        case.addCleanup(home.cleanup)
        self.home = Path(home.name)
        acme = self.home / "code" / "ACME"
        (acme / ".git").mkdir(parents=True)
        (self.home / "features.py").write_text(FEATURES)
        (acme / "AGENTS.md").write_text(
            f"---\nfeatures: {sys.executable} {self.home / 'features.py'}\n---\n\n# ACME\n")
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": str(self.home), "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "ESC_REPO": str(REPO)})
        if own:
            env.update({"ESC_OVERLAY": "1", "AGENTKIT_SESSION": own})
        if notice:
            env["ESC_NOTICE"] = notice
        self.keys = "esc leave"
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

    def send(self, keys):
        os.write(self.master, keys)

    def screen(self, where=None, after=0):
        """The last whole screen written over in place that `where` accepts -- the main menu's
        by default -- as it shows, row 1 first."""
        where = where or (lambda lines: any(self.keys in line for line in lines))

        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if where(lines):
                    return lines
            return None
        return self.until(ready, "the screen")

    def press(self, keys, where=None):
        """Keys, then the screen they drew."""
        mark = len(self.text())
        self.send(keys)
        return self.screen(where, after=mark)

    def highlight(self, text):
        """The main screen with the row saying `text` highlighted: up, then down, a key at a
        time, so the screen read is always the last key's."""
        lines = self.screen()
        for key in (b"k",) * 4 + (b"j",) * 8:
            if text in next(line for line in lines if line.startswith("›")):
                return lines
            lines = self.press(key)
        self.case.fail(f"no row says {text}:\n" + "\n".join(lines))

    def back(self, name, where):
        """`q` leaves the screen `where` accepts up, and Esc takes it down within ESC_WAIT; the
        key line under it ends `esc back`, or on the menu itself `esc leave`."""
        if where is not None:
            lines = self.screen(where)
            self.case.assertTrue(lines[-1].endswith("esc leave" if name == "loop" else "esc back"),
                                 lines)
        mark = len(self.text())
        self.send(b"q")
        time.sleep(0.3)
        self.case.assertNotIn(f"<back {name} ", self.text()[mark:])
        mark = len(self.text())
        sent = time.monotonic()
        self.send(ESC)
        found = self.until(lambda text: re.search(rf"<back {name} ([\d.]+)>", text[mark:]),
                           f"{name} back")
        self.case.assertLess(float(found.group(1)) - sent, ESC_WAIT, name)

    def leave(self):
        self.screen()
        self.back("loop", lambda lines: self.keys in lines[-1])
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


class EscBack(unittest.TestCase):
    def test_every_screen_under_the_menu_goes_back_on_esc_and_never_on_q(self):
        menu_ = Menu(self)
        menu_.highlight("alpha")
        menu_.send(b"i")
        menu_.back("show_info", title("info"))
        menu_.send(b"x")                                  # alpha is working: asked under its row
        menu_.back("choose", lambda lines: lines[-1].strip() == "esc back")
        self.assertNotIn("<stopped", menu_.text())
        menu_.highlight("ACME")
        menu_.press(ENTER, title("ACME"))
        menu_.back("show_features", lambda lines: title("ACME")(lines)
                   and any("Dark mode" in line for line in lines))
        menu_.leave()

    def test_the_config_screen_and_every_row_it_opens_go_back_on_esc(self):
        menu_ = Menu(self)
        menu_.screen()
        config_ = title("config")
        menu_.press(b"c", config_)

        def model(lines):             # the first model's own screen, opened from its label
            return (bool(lines) and lines[0].startswith("agentkit · config · ")
                    and any("model id" in line for line in lines))
        menu_.press(LEFT + ENTER, model)
        menu_.back("config_model", model)
        menu_.press(DOWN * 30 + UP * 3, lambda lines: config_(lines) and any(
            line.startswith("›") and "add a model" in line for line in lines))
        menu_.press(ENTER, title("config · add a model"))
        menu_.back("config_add", title("config · add a model"))
        menu_.press(DOWN + ENTER, title("config · add a provider"))
        menu_.back("config_add_provider", title("config · add a provider"))
        menu_.press(RIGHT + ENTER, title("config · remove a provider"))
        menu_.back("config_remove_provider", title("config · remove a provider"))
        menu_.press(DOWN + ENTER, title("config · discord"))
        menu_.back("config_discord", title("config · discord"))
        self.assertEqual(list(menu_.home.rglob("discord_*")), [])   # the typed `q` is not saved
        menu_.back("config_matrix", config_)
        menu_.leave()

    def test_n_goes_back_from_its_name_and_from_its_models(self):
        menu_ = Menu(self)
        menu_.screen()
        mark = len(menu_.text())
        menu_.send(b"n")
        menu_.back("new_session", title("new session"))
        # the name Enter takes is in the field, dim, until a key replaces it
        typed = menu_.text()[mark:]
        self.assertRegex(typed, r"Name: \x1b\[[\d;]*mauto\x1b\[0m")
        self.assertRegex(typed, r"Name: q\x1b\[K")
        mark = len(menu_.text())
        menu_.press(b"n", title("new session"))
        menu_.send(ENTER)                           # auto: the models, on the same keys
        menu_.back("new_session", lambda lines: title("new session")(lines)
                   and "start" in lines[-1])
        menu_.leave()
        self.assertNotIn("<opened", menu_.text())

    def test_the_popup_goes_back_from_rename_and_esc_closes_it(self):
        menu_ = Menu(self, own="alpha")
        menu_.screen()
        mark = len(menu_.text())
        menu_.send(b"r")
        menu_.back("rename_this_session", title("rename"))
        self.assertRegex(menu_.text()[mark:], r"Name: \x1b\[[\d;]*malpha\x1b\[0m")
        self.assertNotIn("<renamed", menu_.text())
        menu_.leave()

    def test_a_notice_waits_for_esc_with_the_terminal_given_back(self):
        menu_ = Menu(self, notice="update: agentkit moved on")
        menu_.until(lambda text: "update: agentkit moved on" in text and "esc back " in text,
                    "the notice")
        menu_.back("pause", None)
        menu_.leave()

    def test_a_screen_waiting_on_a_fetch_lets_q_go_and_goes_back_on_esc(self):
        Key, done = terminal.Key, threading.Event()
        self.addCleanup(done.set)                 # the fetch left to finish on its own
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "frame"), \
                patch.object(menu, "moving", side_effect=[Key("char", "q"), Key("esc")]) as keys:
            with self.assertRaises(menu.Back):
                menu.waited(lambda: done.wait(10), "new session")
        self.assertEqual(keys.call_count, 2)      # `q` was read, and let go

    def test_a_field_edits_and_answers_on_the_keys(self):
        Key = terminal.Key

        def typed(*keys, placeholder=""):
            with patch.object(terminal, "read_key", side_effect=keys), \
                    redirect_stdout(io.StringIO()):
                return terminal.field("Name: ", placeholder)

        self.assertEqual(typed(Key("char", "a"), Key("char", "b"), Key("backspace"),
                               Key("char", "c"), Key("enter")), "ac")
        self.assertEqual(typed(Key("enter"), placeholder="auto"), "")   # the caller's default
        self.assertEqual(typed(Key("char", "q"), Key("esc")), terminal.ESC)
        # wide characters are two cells each: no line drawn is wider than the screen
        with patch.object(terminal, "read_key", side_effect=[Key("char", "界")] * 30
                          + [Key("enter")]), \
                patch.object(terminal, "width", return_value=40), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(terminal.field("Name: ", "a placeholder wider than forty cells"),
                             "界" * 30)
        drawn = [terminal.cells(line) for line in out.getvalue().split("\r") if line]
        self.assertLess(max(drawn), 40, drawn)
        # a paste is drawn once a key and still lets Esc through at once
        with patch.object(terminal, "width", return_value=40):
            began = time.monotonic()
            self.assertEqual(typed(*[Key("char", "a")] * 800, Key("esc")), terminal.ESC)
        self.assertLess(time.monotonic() - began, ESC_WAIT)



class Pipe(Sandbox):
    def test_from_a_pipe_q_is_no_key_and_an_empty_line_or_the_end_goes_back(self):
        answers = iter(["q", ""])
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                patch.object(menu.Live, "probe", lambda self, now=None: False), \
                patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                             wake=None: next(answers)), \
                patch.object(menu, "read", return_value=""), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg), 0)
        self.assertIn("not a key: 'q'", out.getvalue())
        self.assertIn("esc leave", menu.KEYS)
        # the end of input is the empty line that leaves
        with patch.object(terminal, "readline", return_value=None), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.read("> ", ""), "")



class NewSessionKeyboard(Sandbox):
    def test_n_gives_the_menus_own_keyboard_back_before_the_seat_is_made(self):
        # A keyboard `n` took for its usage wait must never stand in for the menu's: the one
        # given back before the seat is made is the menu's, or the seat opens on raw modes.
        events = []

        class MenuKeyboard:
            def give(self):
                events.append("given")
        keyboard = MenuKeyboard()
        with patch.object(orch, "ask_name", return_value="acme"), \
                patch.object(orch, "taken_names", return_value=[]), \
                patch.object(menu, "waited",
                             side_effect=lambda fn, title, keyboard=None:
                             events.append(("waited", keyboard)) or {}), \
                patch.object(orch, "select", return_value=("opus", None, ["opus"], ["astra"])), \
                patch.object(orch, "seat_cwd", return_value=str(self.root)), \
                patch.object(orch, "create", side_effect=lambda *a, **k: events.append("made") or {}), \
                patch.object(menu, "open_session"), patch.object(terminal, "frame"):
            self.assertEqual(menu.new_session({"defaults": {}}, False, keyboard), "acme")
        self.assertEqual(events, [("waited", keyboard), "given", "made"])

if __name__ == "__main__":
    unittest.main(verbosity=2)

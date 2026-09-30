"""The menu inside a session floats over it.

`Ctrl-b m`'s popup has a rounded border in the dim colour with ` agentkit ` set into its top edge
and, but on a phone, a column and a row of padding inside it, a line typed into it included; the
pane behind it draws its text dim while it is up and has exactly its own style back once the last
popup over it is down, however it comes down -- its menu ending, a crash, a kill, which is what
its client going does to it too; and its content fades in on the motion clock, a key pressed
meanwhile answered at once.

tmux is a fake answering as tmux 3.5a: its version, the one pane's options, kept in a file, and
`display-popup`, which runs the popup's command and returns once it is down, as tmux 3.5a's
does however the popup went (as seen on a real one).  The binding is run the way tmux runs it:
the job its `run-shell -b` starts, with the pane and the client expanded into it.  The popup is
a stand-in saying what it saw, and the menu's fade and padding are `menu.loop` on a pty of its
own with the seats faked.  Nothing here starts a tmux server, a seat or a probe; the only
processes signalled are the test's own children.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shlex
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
from agentkit import config, motion, orch, terminal

DIM = f"fg=#{terminal.STATE_STYLES['dim'][2]}"
OWN = "fg=red,bg=blue,bold"         # a style a pane may have of its own

# tmux as far as this test asks it: `-V`; `set`/`show` on the one pane's options; `wait-for`'s
# locks; and `display-popup`, logged, its command run and waited for.  With no pane it answers
# what tmux answers with no server up.
FAKE_TMUX = r"""#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
if args == ["-V"]:
    print(os.environ.get("FAKE_TMUX_VERSION", "tmux 3.5a"))
    sys.exit(0)
while args[:1] in (["-L"], ["-S"], ["-f"]):
    args = args[2:]
pane = Path(os.environ.get("FAKE_TMUX_PANE") or "/nonexistent/pane.json")
if not pane.parent.is_dir():
    print(f"no server running on /tmp/tmux-{os.getuid()}/default", file=sys.stderr)
    sys.exit(1)
listed = [[]]
for arg in args:
    listed.append([]) if arg == ";" else listed[-1].append(arg)
for command, *given in listed:
    flags, words, values, rest = "", [], {}, iter(given)
    for arg in rest:
        if arg.startswith("-") and not words:
            flags += arg[1:]
            if arg[-1] in ("bcdehSsTtwxy" if command == "display-popup" else "t"):
                values.setdefault(arg[-1], []).append(next(rest))
        else:
            words.append(arg)
    options = json.loads(pane.read_text()) if pane.exists() else {}
    if command in ("show-options", "show") and "p" in flags:
        for name in words or sorted(options):
            if name in options:
                print(options[name] if "v" in flags else name + " " + (options[name] or "''"))
    elif command in ("set-option", "set") and "p" in flags:
        if "u" in flags:
            options.pop(words[0], None)
        else:
            options[words[0]] = words[1]
        written = pane.with_name(f"pane-{os.getpid()}.json")
        written.write_text(json.dumps(options))
        os.replace(written, pane)       # whole, for whoever reads it meanwhile
    elif command == "wait-for":
        lock = pane.with_name(f"lock-{words[0]}")
        while "L" in flags:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
                break
            except FileExistsError:
                time.sleep(0.01)        # held: wait, as a second `wait-for -L` does
        if "U" in flags:
            lock.unlink(missing_ok=True)
    elif command == "display-popup":
        with open(os.environ["FAKE_TMUX_POPUPS"], "a") as log:
            log.write(json.dumps(given) + "\n")
        env = dict(os.environ, **dict(value.split("=", 1) for value in values.get("e", [])))
        subprocess.run(words[-1], shell=True, env=env)
    else:
        print(f"unknown command {command}", file=sys.stderr)
        sys.exit(1)
"""

# The popup's command: says what style the pane under it has, what it was handed and who it is,
# then ends the way STANDIN_END says -- or waits to be killed.
STANDIN = r"""
import json, os, subprocess, sys, time
style = subprocess.run(["tmux", "show-options", "-pv", "window-style"],
                       capture_output=True, text=True).stdout.strip()
saw = os.environ["STANDIN_SAW"]
with open(saw + ".part", "w") as out:
    json.dump({"style": style, "padding": os.environ.get("AGENTKIT_PADDING"), "pid": os.getpid()},
              out)
os.replace(saw + ".part", saw)
end = os.environ["STANDIN_END"]
if end == "crash":
    raise SystemExit(70)
if end == "kill":
    time.sleep(60)
"""

# The overlay: the real loop, draw, clock and key reader; the seats and what opening does faked.
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["FLOATS_REPO"])
from agentkit import config, menu, orch, terminal

orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0} for name in ("seat-a", "seat-b")]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "", "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>", flush=True)
terminal.inset()                  # what `ak attach --overlay` does first
sys.exit(menu.loop(config.load(), dry_run=True, overlay=True))
"""
# A line read inside the popup, the way `r` and `n` read one, and what is written after it.
LINE_CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["FLOATS_REPO"])
from agentkit import terminal

terminal.inset()
print(f"<answered {terminal.readline('Name: ')!r}>", flush=True)
"""
TAKEN, DOWN = "\x1b[?1049h", b"\x1b[B"
PANE, CLIENT = "%1", "/dev/pts/7"   # what the binding's formats come to in this test's tmux


def tmux_words(text):
    """A tmux line's words as tmux reads them: '...' as it is, "..." with its backslashes taken
    out, anything else up to a space."""
    return [m[1] if m[1] is not None else re.sub(r"\\(.)", r"\1", m[2]) if m[2] is not None
            else m[3] for m in re.finditer(r"'([^']*)'|\"((?:\\.|[^\"\\])*)\"|(\S+)", text)]


def popup_flags(popup):
    """A `display-popup`'s flags, each to its value (True for one that takes none)."""
    flags, words = {}, iter(popup[:-1])
    for word in words:
        flags[word] = True if word in ("-B", "-C", "-E") else next(words)
    return flags


class FakeTmux:
    """A throwaway HOME whose tmux is the fake, agentkit's tmux.conf written into it."""

    def __init__(self, case, version="tmux 3.5a"):
        home = tempfile.TemporaryDirectory(prefix="popup-floats-")
        case.addCleanup(home.cleanup)
        self.case, self.root, self.opened = case, Path(home.name), 0
        (self.root / "bin").mkdir()
        tmux = self.root / "bin" / "tmux"
        tmux.write_text(FAKE_TMUX)
        tmux.chmod(0o755)
        standin = self.root / "standin.py"
        standin.write_text(STANDIN)
        self.pane, self.log = self.root / "pane.json", self.root / "popups.jsonl"
        self.env = {**os.environ, "HOME": str(self.root), "FAKE_TMUX_VERSION": version,
                    "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_TMUX_PANE": str(self.pane), "FAKE_TMUX_POPUPS": str(self.log)}
        with patch.dict(os.environ, self.env), \
                patch.object(config, "HOME", self.root / ".agentkit"), \
                patch.object(config, "STATE", self.root / ".agentkit" / "state"), \
                patch.object(orch, "popup_command",
                             return_value=shlex.join([sys.executable, str(standin)])):
            for name in ("RUNS", "WT", "SECRETS", "TMP", "ENV", "WORK"):
                self.case.enterContext(patch.object(config, name, self.root / name.lower()))
            self.lines = orch.tmux_conf().read_text().splitlines()

    def branches(self):
        """(phone's, larger screen's) commands the binding runs."""
        bind = tmux_words(next(line for line in self.lines if line.startswith("bind-key m ")))
        self.case.assertEqual(bind[:4], ["bind-key", "m", "if-shell", "-F"])
        return bind[5], bind[6]

    def popups(self):
        """What each `display-popup` so far asked for."""
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def options(self):
        return json.loads(self.pane.read_text()) if self.pane.exists() else {}

    def start(self, small=False, end="exit"):
        """`Ctrl-b m` on a client that is a phone (`small`) or not, as tmux 3.5a runs it: the job
        its `run-shell -b` starts, the pane and the client expanded into it, and where the popup
        will say what it saw.  `end` is how the popup comes down: its menu ending (`exit`), a
        crash (`crash`), or a kill (`kill`, at `down`) -- what `display-popup -C` and a client
        going do to it as well."""
        self.opened += 1
        saw = self.root / f"saw-{self.opened}.json"
        run = tmux_words(self.branches()[0 if small else 1])
        self.case.assertEqual(run[:2], ["run-shell", "-b"])
        script = re.sub(r"##|#\{(pane_id|client_name)\}",
                        lambda m: {"pane_id": PANE, "client_name": CLIENT}.get(m[1], "#"), run[2])
        job = subprocess.Popen(["sh", "-c", script], start_new_session=True,
                               stderr=subprocess.DEVNULL,       # as `run-shell` has it
                               env={**self.env, "STANDIN_SAW": str(saw), "STANDIN_END": end})
        self.case.addCleanup(lambda: job.poll() is None and os.killpg(job.pid, signal.SIGKILL))
        return job, saw

    def seen(self, saw):
        """What a popup `start` began saw, once it has said."""
        deadline = time.monotonic() + 15
        while not saw.exists():
            self.case.assertLess(time.monotonic(), deadline, "the popup never said what it saw")
            time.sleep(0.02)
        seen = json.loads(saw.read_text())
        self.case.addCleanup(self._gone, seen["pid"])
        return seen

    def open(self, small=False, end="exit"):
        job, saw = self.start(small, end)
        return job, self.seen(saw)

    @staticmethod
    def _gone(pid):
        try:
            os.kill(pid, signal.SIGKILL)      # a stand-in of this test's, left waiting
        except ProcessLookupError:
            pass

    def down(self, job, seen, end="exit"):
        """The popup `open` began comes down, and its job ends."""
        if end == "kill":
            os.kill(seen["pid"], signal.SIGKILL)
        self.case.assertEqual(job.wait(15), 0)   # nothing for tmux to show over the pane

    def press(self, small=False, end="exit"):
        job, seen = self.open(small, end)
        self.down(job, seen, end)
        return seen


class TheBinding(unittest.TestCase):
    def test_it_asks_for_a_rounded_dim_border_the_title_and_padding_but_on_a_phone(self):
        tmux = FakeTmux(self)
        tmux.press(small=True)
        tmux.press()
        phone, larger = (popup_flags(popup) for popup in tmux.popups())
        for flags in (phone, larger):
            self.assertEqual(flags["-b"], "rounded")
            self.assertEqual(flags["-S"], DIM)
            self.assertEqual(flags["-T"], " agentkit ")
            self.assertIs(flags["-E"], True)
            self.assertEqual((flags["-c"], flags["-t"]), (CLIENT, PANE))
        self.assertEqual((phone["-w"], phone["-h"]), ("100%", "100%"))
        self.assertNotIn("-e", phone)                        # a phone spares no cell
        self.assertEqual(larger["-e"], f"{terminal.PAD_ENV}=1")
        self.assertNotIn("set-hook", "\n".join(tmux.lines))   # no other session is touched

    def test_a_tmux_without_them_gets_the_plain_popup_and_no_word_about_it(self):
        tmux = FakeTmux(self, version="tmux 3.2a")
        for branch in tmux.branches():
            words = tmux_words(branch)
            self.assertEqual(words[0], "display-popup")
            self.assertFalse({"-b", "-S", "-T", "-e"} & set(words), words)
        self.assertNotIn("window-style", "\n".join(tmux.lines))


class ThePaneBehind(unittest.TestCase):
    def test_opening_dims_it_and_closing_puts_its_own_style_back_however_the_popup_goes(self):
        tmux = FakeTmux(self)
        for own in ({}, {"window-style": OWN}, {"window-style": ""}):   # none, its own, empty
            tmux.pane.write_text(json.dumps(own))
            for small in (False, True):
                for end in ("exit", "crash", "kill"):
                    with self.subTest(own=own, small=small, end=end):
                        seen = tmux.press(small, end)
                        self.assertEqual(seen["style"], DIM)
                        self.assertEqual(seen["padding"], None if small else "1")
                        self.assertEqual(tmux.options(), own)   # exactly: nothing more, nothing less

    def test_it_stays_dim_until_the_last_popup_over_it_is_down_however_they_race(self):
        tmux = FakeTmux(self)
        for own in ({}, {"window-style": OWN}, {"window-style": ""}):
            tmux.pane.write_text(json.dumps(own))
            with self.subTest(own=own, race="opened in the same instant"):
                started = [tmux.start(end="kill"), tmux.start(small=True, end="kill")]
                first, second = ((job, tmux.seen(saw)) for job, saw in started)
                self.assertEqual(second[1]["style"], DIM)
                tmux.down(*first, end="kill")
                self.assertEqual(tmux.options()["window-style"], DIM)   # the second is still up
                tmux.down(*second, end="kill")
                self.assertEqual(tmux.options(), own)
            with self.subTest(own=own, race="closed in the same instant"):
                both = [tmux.open(end="kill"), tmux.open(small=True, end="kill")]
                for _, seen in both:
                    os.kill(seen["pid"], signal.SIGKILL)
                for job, _ in both:
                    self.assertEqual(job.wait(15), 0)
                self.assertEqual(tmux.options(), own)


class Popup:
    """One overlay menu on a pty of its own, and when each byte of what it wrote arrived."""

    def __init__(self, case, padding=0, rows=30, cols=90, child=CHILD):
        self.case = case
        fake = FakeTmux(case)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in fake.env.items()
               if key not in ("NO_COLOR", "COLUMNS", "LINES", "TMUX", "FAKE_TMUX_PANE",
                              terminal.PAD_ENV)}
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "FLOATS_REPO": str(REPO)})
        if padding:
            env[terminal.PAD_ENV] = str(padding)
        self.proc = subprocess.Popen([sys.executable, "-c", child], stdin=self.slave,
                                     stdout=self.slave, stderr=self.slave, env=env,
                                     start_new_session=True)
        self.output, self.arrived, self.lock = b"", [], threading.Lock()
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
                self.arrived.append((len(self.output.decode("utf-8", "replace")), time.monotonic()))

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

    def when(self, offset):
        """When the text up to `offset` had arrived."""
        with self.lock:
            return next(at for end, at in self.arrived if end >= offset)

    def until(self, pattern, what, after=0, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            found = re.compile(pattern, re.S).search(self.text(), after)
            if found:
                return found
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {what}:\n{self.text()[-3000:]!r}")
            time.sleep(0.002)


class TheContent(unittest.TestCase):
    def test_it_fades_in_from_the_background_over_about_120_ms_and_is_then_as_drawn(self):
        popup = Popup(self)
        up = popup.until(r"\x1b\[1;1Hagentkit", "the header as drawn")
        text = popup.text()[:up.start()]
        tones = [(int(m[1]), m.start()) for m in
                 re.finditer(r"\x1b\[1;1H\x1b\[38;2;(\d+);\1;\1m", text)]
        self.assertGreaterEqual(len(tones), 2, repr(text[-2000:]))
        self.assertLess(tones[0][0], 40)                     # out of the dark background
        self.assertEqual([tone for tone, _ in tones], sorted(tone for tone, _ in tones))
        self.assertLess(tones[0][0], tones[-1][0])
        self.assertNotIn("\x1b[Kagentkit", text)             # never first drawn as it is
        took = popup.when(up.end()) - popup.when(tones[0][1] + 1)
        self.assertGreaterEqual(took, motion.FADE - 0.03)
        self.assertLess(took, motion.FADE + 1)

    def test_a_key_pressed_while_it_fades_in_is_answered_within_100_ms(self):
        popup = Popup(self)
        popup.until(r"\x1b\[1;1H\x1b\[38;2;", "the first frame coming up")
        mark, sent = len(popup.text()), time.monotonic()
        os.write(popup.master, DOWN)
        highlighted = r"›(?:\s|\x1b\[[0-9;]*m)*2(?:\s|\x1b\[[0-9;]*m)+seat-b"
        found = popup.until(highlighted, "seat-b highlighted", after=mark)
        self.assertLess(popup.when(found.end()) - sent, 0.1)
        # still coming up after it: the key was pressed during the fade, and did not end it
        self.assertRegex(popup.text()[found.start():], r"\x1b\[\d+;1H\x1b\[38;2;")
        os.write(popup.master, b"q")
        self.assertEqual(popup.proc.wait(15), 0, popup.text()[-2000:])

    def test_padded_it_draws_a_row_and_a_column_in_and_reads_a_click_back(self):
        rows, cols = 30, 90
        popup = Popup(self, padding=1, rows=rows, cols=cols)
        up = popup.until(r"\x1b\[2;2Hagentkit", "the header as drawn, a cell in")
        drawn = popup.text()[popup.text().index(TAKEN):up.end()]
        self.assertNotRegex(drawn, r"\x1b\[1;\d+H|\x1b\[\d+;1H")   # nothing on the padding
        seat = popup.until(r"\x1b\[(\d+);2H((?:(?!\x1b\[\d+;\d+H).)*seat-b)", "seat-b's row",
                           after=up.start())
        self.assertLessEqual(terminal.cells(terminal.ANSI.sub("", seat[2])), cols - 2)
        row = int(seat[1])
        os.write(popup.master, f"\x1b[<0;6;{row}M\x1b[<0;6;{row}m".encode())
        popup.until(r"<opened seat-b>", "seat-b opened by its click")
        self.assertEqual(popup.proc.wait(15), 0, popup.text()[-2000:])

    def test_padded_what_follows_a_typed_line_starts_a_column_in(self):
        popup = Popup(self, padding=1, child=LINE_CHILD)
        popup.until(r"\x1b\[2;2HName: ", "the question, a cell in")
        os.write(popup.master, b"taken\r")
        # the terminal echoes the Enter back to column 1; what is written next is in again
        popup.until(r"taken\r\n\r\x1b\[2G<answered 'taken'>", "the answer, a column in")
        self.assertEqual(popup.proc.wait(15), 0, popup.text()[-2000:])


if __name__ == "__main__":
    unittest.main()

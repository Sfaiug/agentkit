"""The menu inside a session floats over it.

`Ctrl-b m`'s popup has a rounded border in the dim colour with ` agentkit ` set into its top edge
and, but on a phone, a column and a row of padding inside it; the pane behind it draws its text
dim while it is up and has its own style back however the popup comes down -- its menu ending, a
crash, a kill, its client going; and its content fades in on the motion clock, a key pressed
meanwhile answered at once.

tmux is a fake answering as tmux 3.5a: its version, and the one pane's options, kept in a file.
The binding is run the way tmux 3.5a runs it (as seen on a real one): its commands in order,
`display-popup` holding the rest until its popup is down, and a client lost with the popup up
dropping the rest for the `client-detached` hook.  The popup is a stand-in saying what it saw,
and the menu's fade and padding are `menu.loop` on a pty of its own with the seats faked.
Nothing here starts a tmux server, a seat or a probe; the only processes signalled are the
test's own children.
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

# tmux as far as this test asks it: `-V`, and `set`/`show` on the one pane's options; to
# anything else it answers what tmux answers with no server up.
FAKE_TMUX = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
if args == ["-V"]:
    print(os.environ.get("FAKE_TMUX_VERSION", "tmux 3.5a"))
    sys.exit(0)
while args[:1] in (["-L"], ["-S"], ["-f"]):
    args = args[2:]
pane = Path(os.environ.get("FAKE_TMUX_PANE") or "/nonexistent/pane.json")
command, flags, words, rest = (args or [""])[0], "", [], iter(args[1:])
for arg in rest:
    if arg.startswith("-") and not words:
        flags += arg[1:]
        if "t" in arg:
            next(rest, None)           # the pane: there is only the one
    else:
        words.append(arg)
if (command in ("set-option", "set", "show-options", "show") and "p" in flags
        and pane.parent.is_dir()):
    options = json.loads(pane.read_text()) if pane.exists() else {}
    if command.startswith("show"):
        for name in words or sorted(options):
            if name in options:
                print(options[name] if "v" in flags else f"{name} {options[name]}")
    elif "u" in flags:
        options.pop(words[0], None)
    else:
        options[words[0]] = words[1]
    pane.write_text(json.dumps(options))
    sys.exit(0)
print(f"no server running on /tmp/tmux-{os.getuid()}/default", file=sys.stderr)
sys.exit(1)
"""

# The popup's command: says what style the pane under it has and what it was handed, then ends
# the way STANDIN_END says -- or waits to be killed.
STANDIN = r"""
import json, os, subprocess, sys, time
style = subprocess.run(["tmux", "show-options", "-pv", "window-style"],
                       capture_output=True, text=True).stdout.strip()
padding = os.environ.get("AGENTKIT_PADDING")
open(os.environ["STANDIN_SAW"], "w").write(json.dumps({"style": style, "padding": padding}))
end = os.environ["STANDIN_END"]
if end == "crash":
    raise SystemExit(70)
if end in ("kill", "lost"):
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
TAKEN, DOWN = "\x1b[?1049h", b"\x1b[B"


def tmux_words(text):
    """A tmux line's words as tmux reads them: '...' as it is, "..." with its backslashes taken
    out, anything else up to a space."""
    return [m[1] if m[1] is not None else re.sub(r"\\(.)", r"\1", m[2]) if m[2] is not None
            else m[3] for m in re.finditer(r"'([^']*)'|\"((?:\\.|[^\"\\])*)\"|(\S+)", text)]


def commands(text):
    """A command list's commands, each its words: tmux splits a list at a `;` word."""
    listed = [[]]
    for word in tmux_words(text):
        if word == ";":
            listed.append([])
        else:
            listed[-1].append(word)
    return listed


def popup_flags(command):
    """A `display-popup`'s flags, each to its value (True for one that takes none)."""
    flags, words = {}, iter(command[1:-1])
    for word in words:
        flags[word] = True if word in ("-B", "-C", "-E") else next(words)
    return flags


class FakeTmux:
    """A throwaway HOME whose tmux is the fake, agentkit's tmux.conf written into it."""

    def __init__(self, case, version="tmux 3.5a"):
        home = tempfile.TemporaryDirectory(prefix="popup-floats-")
        case.addCleanup(home.cleanup)
        self.case, self.root = case, Path(home.name)
        (self.root / "bin").mkdir()
        tmux = self.root / "bin" / "tmux"
        tmux.write_text(FAKE_TMUX)
        tmux.chmod(0o755)
        standin = self.root / "standin.py"
        standin.write_text(STANDIN)
        self.pane, self.saw = self.root / "pane.json", self.root / "saw.json"
        self.env = {**os.environ, "HOME": str(self.root), "FAKE_TMUX_VERSION": version,
                    "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_TMUX_PANE": str(self.pane), "STANDIN_SAW": str(self.saw)}
        with patch.dict(os.environ, self.env), \
                patch.object(config, "HOME", self.root / ".agentkit"), \
                patch.object(config, "STATE", self.root / ".agentkit" / "state"), \
                patch.object(orch, "popup_command",
                             return_value=shlex.join([sys.executable, str(standin)])):
            for name in ("RUNS", "WT", "SECRETS", "TMP", "ENV", "WORK"):
                self.case.enterContext(patch.object(config, name, self.root / name.lower()))
            self.lines = orch.tmux_conf().read_text().splitlines()

    def line(self, start):
        return next(line for line in self.lines if line.startswith(start))

    def popups(self):
        """(phone's, larger screen's) `display-popup`, each its words."""
        bind = tmux_words(self.line("bind-key m "))
        self.case.assertEqual(bind[:4], ["bind-key", "m", "if-shell", "-F"])
        return tuple(next(command for command in commands(branch) if command[0] == "display-popup")
                     for branch in bind[5:7])

    def tmux(self, *args):
        return subprocess.run(["tmux", *args], env=self.env, capture_output=True, text=True,
                              check=True).stdout.strip()

    def style(self):
        return self.tmux("show-options", "-pv", "window-style")

    def press(self, small=False, end="exit"):
        """`Ctrl-b m` on a client that is a phone (`small`) or not, as tmux 3.5a runs it, and what
        the popup saw.  `end` is how the popup comes down: its menu ending (`exit`), a crash
        (`crash`), a kill (`kill`), or its client going with the popup up (`lost`), which drops
        whatever the binding had left and runs the `client-detached` hook instead."""
        self.saw.unlink(missing_ok=True)
        bind = tmux_words(self.line("bind-key m "))
        for command in commands(bind[5 if small else 6]):
            if command[0] != "display-popup":
                self.tmux(*command)
                continue
            flags = popup_flags(command)
            env = {**self.env, "STANDIN_END": end}
            env.update([flags["-e"].split("=", 1)] if "-e" in flags else [])
            popup = subprocess.Popen(command[-1], shell=True, env=env, start_new_session=True)
            self.case.addCleanup(
                lambda: popup.poll() is None and os.killpg(popup.pid, signal.SIGKILL))
            deadline = time.monotonic() + 15
            while not self.saw.exists() or not self.saw.read_text():
                self.case.assertLess(time.monotonic(), deadline, "the popup never said what it saw")
                time.sleep(0.02)
            if end in ("kill", "lost"):
                os.killpg(popup.pid, signal.SIGKILL)   # its own group: what tmux takes down
            popup.wait(15)
            if end == "lost":
                for hook in commands(tmux_words(self.line("set-hook -g client-detached "))[-1]):
                    self.tmux(*hook)
                break
        return json.loads(self.saw.read_text())


class TheBinding(unittest.TestCase):
    def test_it_asks_for_a_rounded_dim_border_the_title_and_padding_but_on_a_phone(self):
        phone, larger = FakeTmux(self).popups()
        for popup in (phone, larger):
            flags = popup_flags(popup)
            self.assertEqual(flags["-b"], "rounded")
            self.assertEqual(flags["-S"], DIM)
            self.assertEqual(flags["-T"], " agentkit ")
            self.assertIs(flags["-E"], True)
        self.assertEqual((popup_flags(phone)["-w"], popup_flags(phone)["-h"]), ("100%", "100%"))
        self.assertNotIn("-e", popup_flags(phone))           # a phone spares no cell
        self.assertEqual(popup_flags(larger)["-e"], f"{terminal.PAD_ENV}=1")

    def test_a_tmux_without_them_gets_the_plain_popup_and_no_word_about_it(self):
        tmux = FakeTmux(self, version="tmux 3.2a")
        for popup in tmux.popups():
            self.assertFalse({"-b", "-S", "-T", "-e"} & set(popup_flags(popup)), popup)
        self.assertNotIn("window-style", "\n".join(tmux.lines))
        self.assertNotIn("set-hook", "\n".join(tmux.lines))


class ThePaneBehind(unittest.TestCase):
    def test_opening_dims_it_and_closing_restores_it_however_the_popup_comes_down(self):
        tmux = FakeTmux(self)
        for small in (False, True):
            for end in ("exit", "crash", "kill", "lost"):
                with self.subTest(small=small, end=end):
                    self.assertEqual(tmux.style(), "")
                    saw = tmux.press(small, end)
                    self.assertEqual(saw["style"], DIM)
                    self.assertEqual(saw["padding"], None if small else "1")
                    self.assertEqual(tmux.style(), "", "the pane keeps the popup's dim")

    def test_a_style_the_pane_never_had_is_not_left_behind(self):
        tmux = FakeTmux(self)
        tmux.press()
        self.assertEqual(json.loads(tmux.pane.read_text()), {})


class Popup:
    """One overlay menu on a pty of its own, and when each byte of what it wrote arrived."""

    def __init__(self, case, padding=0, rows=30, cols=90):
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
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD], stdin=self.slave,
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


if __name__ == "__main__":
    unittest.main()

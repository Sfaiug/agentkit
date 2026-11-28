"""An idle ak screen follows its terminal's background without a key pressed.

The owner (20 Nov 2026): "the background of the terminal which the user has in its setting should
be used, and ak just sits on top of that."  Black-box: `AK_BIN` runs in tmux
(`tests/fixtures/akterm.py`), which answers OSC 11 with its pane's `window-style` background,
and directly on a pty the test answers or leaves silent.  Asserts no duration and no tick count.
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.aklooks import look, looks
from fixtures.akseat import Seat
from fixtures.akterm import KEPT, SERVER, Terminal

ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
QUERY, DA1 = b"\x1b]11;?\x1b\\", b"\x1b[?62;22c"
START_QUERY = QUERY + b"\x1b[c"
DARK_ANSWER = b"\x1b]11;rgb:0000/0000/0000\x1b\\"
WHITE_ANSWER = b"\x1b]11;rgb:ffff/ffff/ffff\x1b\\"
HOLD, RELEASE = b"\x1b[?2026h", b"\x1b[?2026l"
# the accent colour on `›`: white theme (0067c6) and black theme (4da3ff)
WHITE_ACCENT, BLACK_ACCENT = "38;2;0;103;198", "38;2;77;163;255"
ADAPTER = """#!/bin/sh
[ "$1" = interactive ] || exit 1
{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>{asked}
printf '%s' {command}
"""
HARNESS = "sh -c 'echo reopened; exec sleep 300'\n"


def plain(raw):
    return ANSI.sub(b"", raw)


def whole_draws(raw):
    """Every complete whole draw of the ak screen in `raw`, in order."""
    draws, at, marker = [], 0, HOLD + b"\x1b[H"
    while (start := raw.find(marker, at)) >= 0 and (end := raw.find(RELEASE, start)) >= 0:
        at, frame = end + len(RELEASE), raw[start:end + len(RELEASE)]
        if b"esc leave" in plain(frame):
            draws.append(frame)
    return draws


class PtyMenu:
    """`AK` run directly on a pty the test reads and answers itself."""

    def __init__(self, home, env=None, size=(100, 30)):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
        child_env = home._env({"TERM": "xterm-256color", "COLORTERM": "truecolor", **(env or {})})
        for name in ("TMUX", "TMUX_PANE", "NO_COLOR"):
            child_env.pop(name, None)
        self.proc = subprocess.Popen(
            [AK], cwd=str(home.path), env=child_env,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        self.buf = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if self.proc.poll() is not None:
                break
            try:
                os.killpg(self.proc.pid, sig)
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        os.close(self.master)

    def read_until(self, predicate, bound=60):
        deadline = time.monotonic() + bound
        while not predicate(self.buf) and time.monotonic() < deadline:
            if select.select([self.master], [], [], min(0.2, max(0, deadline - time.monotonic())))[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.buf += chunk
        if not predicate(self.buf):
            raise AssertionError(f"predicate never held; tail={plain(self.buf)[-400:]!r}")
        return self.buf

    def wait_shade(self, accent, bound=60):
        want = accent.encode()
        return self.read_until(
            lambda buf: bool(draws := whole_draws(buf)) and want in draws[-1], bound)

    def write(self, data):
        os.write(self.master, data)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnOpenMenuFollowsItsTerminal(unittest.TestCase):
    def set_background(self, home, background):
        done = home.tmux("set-option", "-g", "window-style", f"bg={background}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)

    def wait_accent(self, menu, wanted, bound=60):
        deadline = time.monotonic() + bound
        while True:
            try:
                shown = look(looks(menu.screen(colours=True)), "›") & {WHITE_ACCENT, BLACK_ACCENT}
            except AssertionError:
                shown = set()
            if shown == {wanted} or (left := deadline - time.monotonic()) <= 0:
                return shown
            time.sleep(min(0.1, left))

    def test_akterm_follows_light_and_back_to_dark_without_a_key(self):
        with Home() as home:
            Seat(home, "acme")
            Terminal(home, "--help").exit_code()
            self.set_background(home, "#000000")
            menu = Terminal(home, size=(100, 40), env={"COLORTERM": "truecolor"})
            menu.wait("esc leave", 60)
            for background, accent, kept in (
                (None, BLACK_ACCENT, "dark 000000"),
                ("#ffffff", WHITE_ACCENT, "light ffffff"),
                ("#000000", BLACK_ACCENT, "dark 000000"),
            ):
                if background is not None:
                    self.set_background(home, background)
                self.assertEqual(self.wait_accent(menu, accent), {accent})
                self.assertEqual((home.path / KEPT).read_text().strip(), kept)

    def test_unsolicited_white_answer_is_drawn_in_light_shades_and_not_as_text(self):
        with Home() as home:
            Seat(home, "acme")
            with PtyMenu(home) as pty_menu:
                pty_menu.read_until(lambda buf: START_QUERY in buf)
                pty_menu.write(DARK_ANSWER + DA1)
                pty_menu.wait_shade(BLACK_ACCENT)
                pty_menu.write(WHITE_ANSWER)
                pty_menu.wait_shade(WHITE_ACCENT)
                self.assertEqual((home.path / KEPT).read_text().strip(), "light ffffff")
                self.assertNotIn(b"11;rgb", pty_menu.buf)
                self.assertNotIn(b"rgb:ffff", pty_menu.buf)
                for frame in whole_draws(pty_menu.buf):
                    text = plain(frame)
                    for piece in (b"11;", b"rgb:", b"ffff"):
                        self.assertNotIn(piece, text)

    def test_answer_between_two_digits_on_past_sessions_opens_the_twelfth(self):
        with Home() as home:
            checkout = home.path / "code/acme"
            checkout.mkdir(parents=True)
            self.assertEqual(home.run("git", "init", "-q", str(checkout)).code, 0)
            Seat(home, "fix-api", cwd=checkout, record={"repo": str(checkout)})
            now = time.time()
            for number in range(1, 13):
                name = f"past-{number:02d}"
                home.write(f".agentkit/state/session-{name}.json", {
                    "orchestrator": "fable", "workers": ["fable"], "cwd": str(checkout),
                    "repo": str(checkout), "created": int(now) - 90000, "resumable": True,
                    "conversation": f"conv-{name}", "id_source": "launcher", "session_title": name})
                home.write(f".agentkit/state/seat-{name}.json", {
                    "stopped_at": now - 100 * number, "closed_by_owner": True})
            asked, adapters = home.root / "adapter-asked.log", home.root / "adapters"
            adapters.mkdir()
            adapter = adapters / "claude.sh"
            adapter.write_text(ADAPTER.format(
                python=shlex.quote(sys.executable), asked=shlex.quote(str(asked)),
                command=shlex.quote(HARNESS)))
            adapter.chmod(0o755)
            with PtyMenu(home, env={"AGENTKIT_ADAPTER_DIR": str(adapters)}) as pty_menu:
                pty_menu.read_until(lambda buf: START_QUERY in buf)
                pty_menu.write(DARK_ANSWER + DA1)
                pty_menu.read_until(lambda buf: b"p past" in plain(buf) and b"esc leave" in plain(buf))
                pty_menu.write(b"p")
                pty_menu.read_until(
                    lambda buf: b"past sessions" in plain(buf) and b"esc back" in plain(buf))
                pty_menu.write(b"1" + WHITE_ANSWER + b"2")
                pty_menu.read_until(
                    lambda buf: b"reopened" in plain(buf)
                    and asked.exists() and bool(asked.read_text().splitlines()))
                calls = [json.loads(line) for line in asked.read_text().splitlines()]
                self.assertEqual(len(calls), 1, calls)
                self.assertEqual(calls[0][3], "conv-past-12", calls)
                self.assertEqual(home.tmux("has-session", "-t", "=past-12").code, 0)
                self.assertNotEqual(home.tmux("has-session", "-t", "=past-01").code, 0)
                self.assertEqual((home.path / KEPT).read_text().strip(), "dark 000000")

    def test_pty_that_never_answers_start_is_asked_only_once(self):
        with Home() as home:
            Seat(home, "acme")
            with PtyMenu(home) as pty_menu:
                pty_menu.read_until(lambda buf: START_QUERY in buf)
                pty_menu.wait_shade(BLACK_ACCENT)
                pty_menu.write(WHITE_ANSWER)
                pty_menu.wait_shade(WHITE_ACCENT)
                pty_menu.write(DARK_ANSWER)
                pty_menu.wait_shade(BLACK_ACCENT)
                self.assertEqual(pty_menu.buf.count(QUERY), 1)
                self.assertEqual((home.path / KEPT).read_text().strip(), "dark 000000")


if __name__ == "__main__":
    unittest.main()

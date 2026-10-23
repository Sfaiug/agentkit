"""A seat in an answer-key Home, as ak left it: its record, and a tmux session on ak's server.

The session is the shape ak's own launch gives a seat (the `@ak_orch` mark, the harness pane's
id, `remain-on-exit`, the seat's name in its environment), so the build under test meets the
seats today's ak opened.  Its pane runs tests/fixtures/akpane.py in place of a harness: it shows
a screen, by default a capture of a real one from tests/fixtures, and keeps what is typed into
it, so a test reads what ak typed from the pane's side however ak sent it.

    from fixtures.akbin import Home
    from fixtures.akseat import Seat
    with Home() as home:
        seat = Seat(home, "acme", screen="claude-working-pane.txt")
        seat.show("claude-prompt-pane.txt")
        assert seat.lines() == []
"""

import json
import re
from pathlib import Path
import shlex
import sys
import time
import unicodedata

from .akbin import SOCKET
from .akpane import stamp

FIXTURES = Path(__file__).resolve().parent
PANE = FIXTURES / "akpane.py"
# Colours and titles a screen's capture holds: the pane draws them, and they take no cell.
ESCAPE = re.compile(r"\x1b(?:\[[0-9;:?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
# An open line of a seat's plan, which a seat's own run launch needs: it names no checkout, so
# no check ever ticks it.
PLAN_LINE = "- [ ] The work is done · check: `false` · acme · written 2026-10-23 09:00"


class Seat:
    """`model` names a [models.*] entry of the Home's config; `record` adds to or replaces the
    record's fields; `alive=False` leaves only the record, as a seat tmux lost; `planned=True`
    gives its plan PLAN_LINE.  The pane is the size the screen was captured at."""

    def __init__(self, home, name="acme", *, model="opus", screen="claude-prompt-pane.txt",
                 cwd=None, record=None, alive=True, composer="❯", planned=False):
        self.home, self.name, self.composer = home, name, composer
        self.cwd = Path(cwd or home.path / "code" / name)
        self.cwd.mkdir(parents=True, exist_ok=True)
        panes = home.root / "panes"
        panes.mkdir(exist_ok=True)
        self.screen_file, self.typed_file = panes / f"{name}.txt", panes / f"{name}.typed"
        self.record = {"orchestrator": model, "workers": [model], "cwd": str(self.cwd),
                       "created": int(time.time()) - 600, "conversation": f"conv-{name}",
                       "id_source": "launcher", "resumable": True, "session_title": name,
                       **(record or {})}
        home.write(f".agentkit/state/session-{name}.json", self.record)
        if planned:
            home.write(f".agentkit/state/plan-{name}.md", PLAN_LINE + "\n")
        self.pane = None
        self.screen = self._text(screen)
        self.screen_file.write_text(self.screen, encoding="utf-8")
        if alive:
            self.start()

    def start(self):
        """Open the seat's session, as ak's launch does, and wait for its screen."""
        width, height = _size(self.screen)
        command = shlex.join([sys.executable, str(PANE), str(self.screen_file),
                              str(self.typed_file), self.composer])
        done = self.home.tmux("-f", "/dev/null", "new-session", "-d", "-s", self.name,
                              "-x", str(width), "-y", str(height), "-c", str(self.cwd),
                              "-e", f"AGENTKIT_SESSION={self.name}",
                              "-e", f"AGENTKIT_TMUX_SOCKET={SOCKET}",
                              "-P", "-F", "#{pane_id}", command)
        assert done.code == 0, done.err
        self.pane = done.out.strip()
        target = f"={self.name}:"
        done = self.home.tmux("set-option", "-t", target, "@ak_orch", "1", ";",
                              "set-option", "-t", target, "@ak_harness_pane", self.pane, ";",
                              "set-option", "-t", target, "remain-on-exit", "on")
        assert done.code == 0, done.err
        self._settle()

    def show(self, screen):
        """Put another screen in the pane, as the harness's next frame, and wait for it."""
        self.screen = self._text(screen)
        if self.pane:
            width, height = _size(self.screen)
            done = self.home.tmux("resize-window", "-t", f"={self.name}:", "-x", str(width),
                                  "-y", str(height))
            assert done.code == 0, done.err
        swap = self.screen_file.with_suffix(".swap")
        swap.write_text(self.screen, encoding="utf-8")
        swap.replace(self.screen_file)
        if self.pane:
            self._settle()

    def capture(self):
        """What the pane shows now."""
        return self.home.tmux("capture-pane", "-p", "-t", self.pane).out

    def typed(self):
        """Every key typed into the pane so far, as text, escape sequences and all."""
        try:
            return self.typed_file.read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def lines(self):
        """Each line entered in the pane's composer, oldest first."""
        try:
            entered = self.typed_file.with_name(self.typed_file.name + ".lines").read_text()
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in entered.splitlines()]

    def wait_lines(self, count, bound=30):
        """The lines entered once there are `count` of them: keys reach the pane a moment after
        tmux takes them."""
        deadline = time.monotonic() + bound
        while len(self.lines()) < count:
            if time.monotonic() > deadline:
                raise AssertionError(f"seat {self.name} took {self.lines()}, not {count} lines")
            time.sleep(0.05)
        return self.lines()

    def _text(self, screen):
        """A fixture's file name, a path, or the screen's text itself."""
        if isinstance(screen, str) and "\n" in screen:
            return screen
        # Joining an absolute path onto FIXTURES yields that path unchanged.
        return (FIXTURES / screen).read_text(encoding="utf-8")

    def _settle(self, bound=30):
        """A pane draws a moment after it is told to; wait until its title says it has drawn
        this screen behind every key typed into it so far (tests/fixtures/akpane.py)."""
        deadline = time.monotonic() + bound
        while True:
            typed = self.typed_file.stat().st_size if self.typed_file.exists() else 0
            want = stamp(self.screen.encode("utf-8"), typed)
            title = self.home.tmux("display-message", "-p", "-t", self.pane, "#{pane_title}")
            if title.out.rstrip("\n") == want:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"seat {self.name} never drew its screen:\n{self.capture()}")
            time.sleep(0.05)


def _cells(text):
    """The cells a terminal gives `text`: none for a combining mark, two for a wide one."""
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF"
               else 1 for c in text)


def _size(screen):
    """The pane a screen was captured from: as wide as its widest line, as tall as its lines,
    blank bottom rows included, each ended by a line break."""
    rows = ESCAPE.sub("", screen).removesuffix("\n").split("\n")
    cells = max(_cells(row) for row in rows)
    return max(cells, 20), max(len(rows), 5)

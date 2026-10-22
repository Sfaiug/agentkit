"""The line a highlighted row opens: what got done for `done`, else who builds and who reviews
and three squares for each task in flight.

The owner reads a seat's state from its row and opens the one line under it with the
highlight (the screen approved on 14 Oct 2026, AGENTS.md).  A done seat says what got done,
its plan's last done line; any other that is not asking names each model building ⚒ and
reviewing ◎ its work once, then each task in flight as three squares, build, review and land,
filled as far as it has come, furthest behind first: in working's colour while a model works
on it, dim while it waits.  A run that ended is no task in flight.  Black-box: the program
`AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py), of eight colours so
nothing breathes, beside tests/fixtures/akseat.py's seats and run records like those `ak run`
writes, and this test fails against `/bin/false`.
"""

import re
import subprocess
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow
UNDER = " " * 5     # an open line starts under the row's name
SGR = re.compile(r"\x1b\[([0-9;]*)m|([^\x1b])")
COLOURS = re.compile(r"\x1b\[[0-9;]*m")
LIVE = Path("/proc/sys/kernel/random/boot_id")


def done_line(what):
    return f"- [x] {what} · check: `true` · acme · written 2026-10-02 12:40 · done abc1234"


def alive(pid):
    """A run record's say that its loop is process `pid`, as `ak run` fingerprints it."""
    ticks = int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19])
    return {"pid": pid, "started_at": time.time(),
            "process_identity": {"boot": LIVE.read_text().strip(), "ticks": ticks}}


def opened(screen, name):
    """The row of `name` while highlighted and the line under it, or None."""
    lines = [line.rstrip() for line in COLOURS.sub("", screen).splitlines()] + [""]
    at = next((n for n, line in enumerate(lines) if re.match(rf"› \d+  {name} ", line)), None)
    return None if at is None else (lines[at], lines[at + 1])


def opens(name):
    """A test of a screen: the highlight is on `name` and its line is open."""
    return lambda screen: (opened(screen, name) or ("", ""))[1].startswith(UNDER)


def looks(line):
    """Each character drawn on a captured line, with its colour and whether it is dim."""
    cells, colour, dim = [], None, False
    for codes, char in SGR.findall(line):
        if char:
            cells.append((char, colour, dim))
            continue
        params = [int(code or 0) for code in codes.split(";")]
        while params:
            code = params.pop(0)
            if code == 0:
                colour, dim = None, False
            elif code == 39:
                colour = None
            elif code in (2, 22):
                dim = code == 2
            elif 30 <= code <= 37 or 90 <= code <= 97:
                colour = code
            elif code == 38:            # 38;5;n or 38;2;r;g;b
                size = 2 if params[:1] == [5] else 4
                colour, params = (38, *params[:size]), params[size:]
    return cells


def groups(cells):
    """The runs of squares on a line's looks, each task's own."""
    found, run = [], []
    first = next(n for n, cell in enumerate(cells) if cell[0] == "■")
    for cell in cells[first:] + [(" ", None, False)]:
        if cell[0] != " ":
            run.append(cell)
        elif run:
            found, run = found + [run], []
    return found


@unittest.skipUnless(REAL_TMUX and LIVE.exists(), "no tmux, or no /proc to fingerprint a run")
class OpenLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "spark", "fable"])
        loop = subprocess.Popen(["sleep", "600"])
        cls.addClassCleanup(loop.wait)
        cls.addClassCleanup(loop.kill)
        made = int(time.time()) - 900
        for at, (name, screen, crew) in enumerate((
                ("beta", "claude-prompt-pane.txt", {}),
                ("fix-api", "claude-working-pane.txt", {"workers": ["spark"],
                                                        "reviewers": ["opus"]}),
                ("gamma", "claude-prompt-pane.txt", {"workers": ["spark", "fable"],
                                                     "reviewers": ["fable"]}))):
            Seat(home, name, screen=screen, record={"created": made + 60 * at, **crew})
        home.write(".agentkit/state/plan-beta.md", "# beta\n" + done_line("tidy the readme")
                   + "\n" + done_line("the parser is shipped") + "\n")
        for run, state in (("0900-aaaa", {"state": "running", "step": "reviewer",
                                          **alive(loop.pid)}),
                           ("0901-bbbb", {"state": "running", "step": "executor",
                                          **alive(loop.pid)}),
                           ("0902-cccc", {"state": "waiting", "waiting_on": {"line": "acme"}}),
                           ("0903-dddd", {"state": "queued", **alive(loop.pid)}),
                           ("0904-eeee", {"state": "pass", "step": "merge"})):
            home.write(f".agentkit/runs/20261020-{run}/run.json",
                       {**state, "launched_session": "fix-api"})
        menu = Terminal(home, size=(100, 30), env={"TERM": "xterm"})
        cls.addClassCleanup(menu.exit_code)
        cls.addClassCleanup(menu.keys, "Escape")
        menu.wait(lambda screen: all(word in screen for word in ("✓ done", "● working",
                                                                 "○ idle")), bound=OPENS)
        cls.screens = {}
        # the first row's line opens only once the highlight has moved
        for key, name in (("j", "fix-api"), ("j", "gamma"), ("k", "fix-api"), ("k", "beta")):
            menu.keys(key)
            cls.screens[name] = opened(menu.wait(opens(name)), name)
            if name == "fix-api":
                cls.coloured = menu.screen(colours=True)

    def test_a_done_seat_opens_what_got_done(self):
        row, line = self.screens["beta"]
        self.assertRegex(row, r"✓ done +━+ 2 of 2$")
        self.assertEqual(line, f"{UNDER}the parser is shipped")

    def test_a_working_seat_opens_who_builds_who_reviews_and_its_tasks_squares(self):
        row, line = self.screens["fix-api"]
        self.assertTrue(row.endswith("● working"), row)
        # build moving, build waiting its turn, review moving, then waiting in the landing line
        self.assertEqual(line, f"{UNDER}muse-spark-1.3-contributor ⚒   Opus 5.5 ◎   "
                               "■□□  ■□□  ■■□  ■■■")

    def test_a_square_is_working_s_colour_while_a_model_works_on_it_and_dim_while_it_waits(self):
        lines = self.coloured.splitlines()
        at = next(n for n, line in enumerate(lines) if "fix-api" in COLOURS.sub("", line))
        working = next(look[1:] for look in looks(lines[at]) if look[0] == "●")
        under = looks(lines[at + 1])
        dim = next(look[1:] for look in under if look[0] == "s")        # the crew's own look
        self.assertNotEqual(working, dim)
        tasks = groups(under)
        self.assertEqual(["".join(cell[0] for cell in task) for task in tasks],
                         ["■□□", "■□□", "■■□", "■■■"])
        for number, (task, moving) in enumerate(zip(tasks, (True, False, True, False))):
            for char, *look in task:
                with self.subTest(task=number, char=char):
                    self.assertEqual(tuple(look), working if moving and char == "■" else dim)

    def test_a_seat_at_rest_opens_each_model_once_with_what_it_does(self):
        row, line = self.screens["gamma"]
        self.assertTrue(row.endswith("○ idle"), row)
        self.assertEqual(line, f"{UNDER}muse-spark-1.3-contributor ⚒   Fable 5.1 ⚒◎")


if __name__ == "__main__":
    unittest.main()

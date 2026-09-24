"""A production project's feature switches are in the menu: its heading says how many are hidden,
seat or no seat, and Enter on it opens one screen where the arrow keys and Enter flip them.

Each test runs `menu.loop` in a child process on a pty of its own, in a temporary HOME whose
~/code/ACME names a fake features command in its AGENTS.md: a script answering `list` and `set`
from a JSON file beside it, logging every call, sleeping when told and refusing when told.  The
seat listing, the seats' words, the usage rows and the probe are faked as tests/test_menu_keys.py
fakes them.  Nothing here reaches ssh, a real project or the owner's ~/.agentkit, and the only
process signalled is the test's own child.
"""

import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import terminal

# The child: the real loop, draw, heading, screen and key reader; fakes for what a seat is.
CHILD = r"""
import json, os, sys
sys.path.insert(0, os.environ["FEATURES_REPO"])
from agentkit import config, menu, orch

orch.listing = lambda reconcile=True: [
    {"name": name, "repo": str(config.CODE / "ACME"), "path": "/", "created": 0}
    for name in json.loads(os.environ["FEATURES_SEATS"])]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "", "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>", flush=True)
menu.FEATURES_WAIT = float(os.environ["FEATURES_WAIT"])
sys.exit(menu.loop(config.load()))
"""
# The project's features command, as ACME's scripts/features.py answers: `list` prints every
# row, `set <id> you|everyone on|off` the row as it now stands, or one line on stderr and 1.
FAKE = r"""
import json, subprocess, sys, time
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
rows = json.loads((here / "features.json").read_text())
if sys.argv[1] == "list":
    time.sleep(float((here / "slow").read_text()) if (here / "slow").exists() else 0)
    print(json.dumps(rows))
    with open(here / "calls.log", "a") as log:
        log.write("list answered\n")
elif (here / "refuse").exists():
    print("warning: a line before the reason", file=sys.stderr)
    print((here / "refuse").read_text(), file=sys.stderr)
    sys.exit(1)
elif (here / "hang").exists():    # its own child does the work, and takes its time over it
    subprocess.run(["sh", "-c", f"sleep {(here / 'hang').read_text()}; "
                    f"echo 'set applied late' >> '{here / 'calls.log'}'"])
else:
    feature, who, value = sys.argv[2:]
    row = next(row for row in rows if row["id"] == feature)
    row[who] = value == "on"
    (here / "features.json").write_text(json.dumps(rows))
    print(json.dumps(row))
"""
FEATURES = [
    {"id": "dark", "name": "Dark mode", "you": False, "everyone": False, "you_switchable": True},
    {"id": "beta", "name": "Beta search", "you": True, "everyone": False, "you_switchable": True},
    {"id": "wide", "name": "Wide tables", "you": False, "everyone": True, "you_switchable": True},
    {"id": "fixed", "name": "Pinned rates", "you": False, "everyone": False,
     "you_switchable": False},
]
ESC, UP, DOWN, RIGHT, LEFT, ENTER = b"\x1b", b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D", b"\r"
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")
MENU, SCREEN = "menu", "screen"


class Menu:
    """One child menu on a pty over a HOME with ~/code/ACME: what it wrote, keys sent to it."""

    def __init__(self, case, features=FEATURES, seats=(), rows=40, cols=100, slow=0.0, wait=20):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="features-screen-")
        case.addCleanup(home.cleanup)
        acme = Path(home.name) / "code" / "ACME"
        (acme / ".git").mkdir(parents=True)
        self.fake = Path(home.name) / "fake"
        self.fake.mkdir()
        (self.fake / "features.py").write_text(FAKE)
        (self.fake / "features.json").write_text(json.dumps(features))
        if slow:
            (self.fake / "slow").write_text(str(slow))
        (acme / "AGENTS.md").write_text(
            f"---\nusers: real\nfeatures: {sys.executable} {self.fake / 'features.py'}\n---\n\n"
            "# ACME\n")
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test", "FEATURES_REPO": str(REPO),
                    "FEATURES_SEATS": json.dumps(list(seats)), "FEATURES_WAIT": str(wait)})
        self.started = time.monotonic()
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

    def calls(self):
        try:
            return (self.fake / "calls.log").read_text().splitlines()
        except OSError:
            return []

    def until(self, ready, what, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            found = ready()
            if found:
                return found
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {what}:\n{self.text()[-3000:]!r}")
            time.sleep(0.02)

    def frame(self, kind, where=None, after=0):
        """The last whole screen of that kind written over in place, as the screen shows it,
        row 1 first, once `where` accepts it."""
        def ready():
            for part in reversed(self.text()[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if (any("q leave" in line for line in lines) if kind == MENU
                        else bool(lines) and lines[0].startswith("agentkit · ACME")):
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, f"the {kind}")

    def press(self, keys, kind, where=None):
        """Keys, then the screen they drew."""
        mark = len(self.text())
        os.write(self.master, keys)
        return self.frame(kind, where, after=mark)

    def opened(self):
        """Enter on the highlighted heading, and the screen once the rows are on it."""
        return self.press(ENTER, SCREEN, lambda lines: any("Dark mode" in line for line in lines))

    def leave(self, screen=False):
        if screen:
            self.press(ESC, MENU)       # Esc goes back from the screen, and `q` leaves the menu
        os.write(self.master, b"q")
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


def has(text):
    return lambda lines: any(text in line for line in lines)


def marks(lines, name):
    """The marks on `name`'s row: under `you`, then under `everyone`."""
    line = next(line for line in lines if name in line)
    return [token for token in line.split() if token in ("●", "○", "—")]


def highlighted(lines):
    marked = [line for line in lines if line.startswith("›")]
    assert len(marked) == 1, lines
    return marked[0]


class FeaturesScreen(unittest.TestCase):
    def test_a_project_naming_its_switches_is_listed_with_no_seat(self):
        menu = Menu(self)
        lines = menu.frame(MENU, has("ACME · 3 hidden features"))
        self.assertEqual(highlighted(lines), "› ACME · 3 hidden features")   # a row to land on
        self.assertNotIn("no sessions", "\n".join(lines))
        menu.opened()
        lines = menu.press(ESC, MENU)
        self.assertEqual(highlighted(lines), "› ACME · 3 hidden features")
        menu.leave()

    def test_a_seat_s_project_heading_counts_them_too(self):
        menu = Menu(self, seats=["fix-api"])
        lines = menu.frame(MENU, has("ACME · 3 hidden features"))
        self.assertEqual(sum("ACME" in line for line in lines), 1)     # one heading, not two
        heading = next(n for n, line in enumerate(lines) if "ACME" in line)
        self.assertIn("fix-api", lines[heading + 1])
        self.assertIn("fix-api", highlighted(lines))      # a seat is highlighted before a heading
        lines = menu.press(UP, MENU, lambda lines: "ACME" in highlighted(lines))
        self.assertTrue(lines[heading].startswith("› ACME"), lines)
        lines = menu.opened()
        self.assertEqual(lines[0].split()[:3], ["agentkit", "·", "ACME"])
        menu.press(ESC, MENU)
        mark = len(menu.text())
        os.write(menu.master, DOWN + ENTER)               # Enter on the seat still opens the seat
        menu.until(lambda: "<opened fix-api>" in menu.text()[mark:], "the seat opened")
        menu.leave()

    def test_the_count_is_the_features_off_for_everyone(self):
        for rows, heading in (([{**FEATURES[0], "everyone": True}, FEATURES[2]], "ACME"),
                              ([FEATURES[0], FEATURES[2]], "ACME · 1 hidden feature")):
            menu = Menu(self, features=rows)
            menu.opened()                                 # the list has landed
            lines = menu.press(ESC, MENU)
            self.assertEqual(highlighted(lines), f"› {heading}")
            menu.leave()

    def test_a_flip_calls_set_and_draws_the_row_it_answers(self):
        menu = Menu(self)
        lines = menu.opened()
        self.assertEqual(lines[2].split(), ["you", "everyone"])
        self.assertIn("Dark mode", highlighted(lines))
        self.assertEqual(marks(lines, "Dark mode"), ["○", "○"])
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ flip   esc back")
        # the project renames it meanwhile: the row drawn is the one `set` answers with
        rows = json.loads((menu.fake / "features.json").read_text())
        rows[0]["name"] = "Dark mode, renamed"
        (menu.fake / "features.json").write_text(json.dumps(rows))
        lines = menu.press(ENTER, SCREEN, has("Dark mode, renamed"))
        self.assertIn("set dark you on", menu.calls())
        self.assertEqual(marks(lines, "Dark mode"), ["●", "○"])
        lines = menu.press(RIGHT + b" ", SCREEN,
                           lambda lines: marks(lines, "Dark mode") == ["●", "●"])
        self.assertIn("set dark everyone on", menu.calls())
        number, line = next((n, line) for n, line in enumerate(lines, 1) if "Beta search" in line)
        column = line.rindex("○") + 1                     # a click on beta's `everyone` flips it
        mark = len(menu.text())
        os.write(menu.master, f"\x1b[<0;{column};{number}M\x1b[<0;{column};{number}m".encode())
        menu.frame(SCREEN, lambda lines: marks(lines, "Beta search") == ["●", "●"], after=mark)
        self.assertIn("set beta everyone on", menu.calls())
        lines = menu.press(ESC, MENU)
        self.assertEqual(highlighted(lines), "› ACME · 1 hidden feature")
        menu.leave()

    def test_a_failing_set_keeps_the_mark(self):
        menu = Menu(self)
        menu.opened()
        (menu.fake / "refuse").write_text("only the owner may switch dark\n")
        before = (menu.fake / "features.json").read_text()
        lines = menu.press(ENTER, SCREEN, has("only the owner may switch dark"))
        self.assertIn("set dark you on", menu.calls())
        self.assertEqual(marks(lines, "Dark mode"), ["○", "○"])
        self.assertEqual(lines[-4:-2], ["", "  only the owner may switch dark"])   # one dim line
        self.assertEqual((menu.fake / "features.json").read_text(), before)
        lines = menu.press(DOWN, SCREEN, lambda lines: "Beta search" in highlighted(lines))
        self.assertFalse(has("only the owner")(lines))   # until the next key
        menu.leave(screen=True)

    def test_a_set_past_its_timeout_is_stopped_with_all_it_started(self):
        menu = Menu(self, wait=1)
        menu.opened()
        (menu.fake / "hang").write_text("2")
        lines = menu.press(ENTER, SCREEN, has("set: no answer in 1.0 s"))
        self.assertEqual(marks(lines, "Dark mode"), ["○", "○"])
        time.sleep(2.5)                                   # past when its child would have done it
        self.assertIn("set dark you on", menu.calls())
        self.assertNotIn("set applied late", menu.calls())
        menu.leave(screen=True)

    def test_a_feature_not_switchable_for_you_shows_a_dash(self):
        menu = Menu(self)
        lines = menu.opened()
        self.assertEqual(marks(lines, "Pinned rates"), ["—", "○"])
        lines = menu.press(DOWN * 3 + ENTER, SCREEN,
                           lambda lines: "Pinned rates" in highlighted(lines))
        time.sleep(0.5)
        self.assertNotIn("set fixed you on", menu.calls())       # nothing to flip there
        lines = menu.press(RIGHT + ENTER, SCREEN,
                           lambda lines: marks(lines, "Pinned rates") == ["—", "●"])
        self.assertIn("set fixed everyone on", menu.calls())
        menu.leave(screen=True)

    def test_on_for_everyone_is_on_for_you(self):
        menu = Menu(self)
        lines = menu.opened()
        self.assertEqual(marks(lines, "Wide tables"), ["●", "●"])
        self.assertEqual(marks(lines, "Beta search"), ["●", "○"])
        # off for everyone, and on for you only where you had it on
        lines = menu.press(DOWN * 2 + RIGHT + ENTER, SCREEN,
                           lambda lines: marks(lines, "Wide tables") == ["○", "○"])
        self.assertIn("set wide everyone off", menu.calls())
        menu.leave(screen=True)

    def test_a_slow_list_never_blocks_a_draw(self):
        menu = Menu(self, slow=5)
        lines = menu.frame(MENU, has("ACME"))
        self.assertLess(time.monotonic() - menu.started, 4)
        self.assertNotIn("list answered", menu.calls())           # asked, and not answered yet
        self.assertEqual(highlighted(lines), "› ACME")
        lines = menu.press(ENTER, SCREEN, has("asking for its features"))
        self.assertNotIn("list answered", menu.calls())
        lines = menu.press(DOWN, SCREEN, has("asking for its features"))   # keys still answered
        # the answer is drawn when it lands, with no key pressed
        menu.until(lambda: "list answered" in menu.calls(), "the slow list", timeout=20)
        lines = menu.frame(SCREEN, has("Dark mode"))
        lines = menu.press(ESC, MENU, has("ACME · 3 hidden features"))
        menu.leave()

    def test_a_phone_draws_both_in_forty_columns(self):
        menu = Menu(self, seats=["fix-api"], rows=24, cols=40)
        lines = menu.frame(MENU, has("ACME · 3 hidden features"))
        lines = menu.press(UP, MENU, lambda lines: "ACME" in highlighted(lines))
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        lines = menu.opened()
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(marks(lines, "Pinned rates"), ["—", "○"])
        (menu.fake / "refuse").write_text("refused: " + "the owner page holds this one " * 20)
        lines = menu.press(ENTER, SCREEN, has("refused: the owner"))
        self.assertLessEqual(len(lines), 23)               # one line, however long the reason
        self.assertEqual(sum("the owner page" in line for line in lines), 1)
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        menu.leave(screen=True)


if __name__ == "__main__":
    unittest.main()

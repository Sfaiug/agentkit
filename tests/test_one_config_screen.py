"""`c` is the one model screen: on a seat its matrix holds that seat's own roles, flipped and
saved to its record, and its row and the next run it starts read the same record; on a heading
only the efforts show; `m` is no key; and `n` starts from what the last session was created
with, the one thing that writes `[defaults]`.

Each test runs `menu.loop` in a child process on a pty of its own, the way
tests/test_session_models_screen.py does, in a temporary HOME holding the shipped config, the
seat `fix-api`'s record and ~/code/ACME, whose AGENTS.md names its feature switches so its
heading is a row.  A `tmux` on PATH writes down each call and answers nothing.  The seat
listing, each seat's word, the usage rows, the meters, the orchestrator switch (it only writes
the record), a seat's harness command, its launch and opening it are faked; the records, the
config file and `orch.create` are real.  Nothing starts a seat or a tmux server, and the only
process signalled is the test's own child.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, terminal

# The child: the real loop, `c` and `n` screens and create; fakes for what a seat is and does.
# Once the menu is left it says what fix-api's next run picks, from fix-api's own environment.
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["ONE_REPO"])
from agentkit import config, menu, orch, run, usage

cfg = config.load()
config.save_session(cfg, "fix-api", "opus", ["opus", "astra"],
                    {"reviewers": ["astra"], "cwd": "/", "created": 0})
orch.listing = lambda reconcile=True: [{"name": "fix-api", "repo": None, "path": "/",
                                        "created": 0}]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "",
                                                     "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
down = usage.Readings({})           # the harnesses ONE_DOWN names are not logged in
down.harnesses = {name: f"{name} is not logged in" for name in os.environ["ONE_DOWN"].split()}
usage.collect = lambda cfg, **kwargs: down
orch.switch_orchestrator = lambda cfg, name, model, providers=None: (
    config.update_session(name, orchestrator=model), "")[1]
orch.fresh_command = lambda cfg, name, seat=None, account=None: (["harness"], None)
config.catalog_now = lambda harness: [{"id": "claude-fable-5-1", "label": "Fable 5.1",
                                       "efforts": ["high", "xhigh", "max"]}]
orch.launch = lambda name, model, *args, **kwargs: print(f"<launched {name} {model}>", flush=True)
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>",
                                                        flush=True)
code = menu.loop(cfg)
os.environ["AGENTKIT_SESSION"] = "fix-api"
picked = run.pick_models(config.load(), usage.Readings({}), None, None, lambda line: None)
print(f"<picks {' '.join(picked)}>", flush=True)
sys.exit(code)
"""
# ACME's features command: one switch, listed.
FEATURES = r"""
import json
print(json.dumps([{"id": "dark", "name": "Dark mode", "you": False, "everyone": False,
                   "you_switchable": True}]))
"""
ESC, UP, DOWN, RIGHT, LEFT = b"\x1b", b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D"
ENTER, SPACE = b"\r", b" "
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


def marks(line):
    return "".join(char for char in line if char in "●○■□")


def highlighted(lines):
    return next(line for line in lines if line.startswith("›"))


def model(lines, name):
    """The `c` row of the model called `name`."""
    return next(line for line in lines if line[2:].split(" ")[0] == name)


def title(name):
    """A screen whose top line is `agentkit · <name>` and the clock, and nothing between."""
    return lambda lines: bool(lines) and re.fullmatch(rf"agentkit · {re.escape(name)} +\d\d:\d\d",
                                                       lines[0])


class Menu:
    """One child menu on a pty: what it wrote so far, keys sent to it, and its HOME."""

    def __init__(self, case, down=""):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="one-config-")
        case.addCleanup(home.cleanup)
        self.home = Path(home.name)
        (self.home / ".agentkit").mkdir()
        self.config = self.home / ".agentkit" / "config.toml"
        self.config.write_text((REPO / "config.default.toml").read_text())
        acme = self.home / "code" / "ACME"
        (acme / ".git").mkdir(parents=True)
        (self.home / "features.py").write_text(FEATURES)
        (acme / "AGENTS.md").write_text(
            f"---\nfeatures: {sys.executable} {self.home / 'features.py'}\n---\n\n# ACME\n")
        self.tmux_calls = self.home / "tmux-calls"
        tmux = self.home / "bin" / "tmux"
        tmux.parent.mkdir()
        tmux.write_text(f'#!/bin/sh\necho "$*" >> {shlex.quote(str(self.tmux_calls))}\nexit 1\n')
        tmux.chmod(0o755)
        (self.home / "adapters").mkdir()
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "PATH": f"{tmux.parent}:{os.environ['PATH']}",
                    "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AGENTKIT_ADAPTER_DIR": str(self.home / "adapters"),
                    "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "ONE_REPO": str(REPO),
                    "ONE_DOWN": down})
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

    def saw(self, text, after=0):
        return self.until(lambda seen: text in seen[after:] and seen, text)

    def screen(self, where=None, after=0):
        """The last whole screen written over in place that `where` accepts -- the main menu's
        by default -- as it shows, row 1 first."""
        where = where or (lambda lines: any("esc leave" in line for line in lines))

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
        """Keys, then the first screen they drew that `where` accepts."""
        mark = len(self.text())
        os.write(self.master, keys)
        return self.screen(where, after=mark)

    def picker(self, where=None, after=0):
        return self.screen(lambda lines: any("space choose" in line for line in lines)
                           and (where is None or where(lines)), after)

    def record(self, name="fix-api"):
        return json.loads((self.home / ".agentkit/state" / f"session-{name}.json").read_text())

    def defaults(self):
        return tomllib.loads(self.config.read_text())["defaults"]

    def leave(self):
        os.write(self.master, ESC)
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])
        calls = self.tmux_calls.read_text().split("\n") if self.tmux_calls.exists() else []
        self.case.assertEqual([call for call in calls if call and "list-sessions" not in call],
                              [])     # tmux was asked what it holds, and nothing else


class OneConfigScreen(unittest.TestCase):
    def test_c_on_a_seat_flips_its_roles_and_its_row_and_next_run_follow(self):
        menu = Menu(self)
        lines = menu.screen()
        self.assertIn("fix-api", highlighted(lines))
        self.assertIn("opus", highlighted(lines).split())
        defaults = menu.defaults()
        lines = menu.press(b"c", title("config · fix-api"))
        self.assertEqual(lines[2].split(), ["orch", "exec", "review", "effort"])
        self.assertEqual(marks(model(lines, "opus")), "●■□")
        self.assertEqual(marks(model(lines, "astra")), "○■■")
        # fable executes, then opus and astra stop: fable alone executes, astra alone reviews
        lines = menu.press(RIGHT + ENTER, lambda lines: marks(model(lines, "fable")) == "○■□")
        self.assertEqual(menu.record()["workers"], ["opus", "astra", "fable"])
        menu.press(DOWN + ENTER + DOWN + ENTER,
                   lambda lines: marks(model(lines, "astra")) == "○□■")
        self.assertEqual(menu.record()["workers"], ["fable"])
        # and fable takes the seat
        lines = menu.press(UP * 2 + LEFT + ENTER,
                           lambda lines: marks(model(lines, "fable")) == "●■□")
        self.assertEqual(marks(model(lines, "opus")), "○□□")
        record = menu.record()
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["fable"], ["astra"]))
        self.assertEqual(menu.defaults(), defaults)       # a seat's marks are its own
        # its row says what `c` says
        lines = menu.press(ESC, lambda lines: any("esc leave" in line for line in lines)
                           and "fable" in highlighted(lines).split())
        self.assertIn("fix-api", highlighted(lines))
        self.assertNotIn("opus", highlighted(lines).split())
        # and so does the next run it starts: its executor and its reviewer
        menu.leave()
        menu.saw("<picks fable astra>")

    def test_a_refusal_is_one_line_and_leaves_the_record_alone(self):
        menu = Menu(self, down="claude")
        menu.screen()
        menu.press(b"c", title("config · fix-api"))
        menu.press(DOWN + RIGHT + RIGHT + SPACE,          # opus joins the reviewers
                   lambda lines: marks(model(lines, "opus")) == "●■■")
        # Claude is down in this child, so astra leaving executes leaves no runnable
        # executor: refused in one line, and the record stays as it was
        lines = menu.press(DOWN + LEFT + SPACE,
                           lambda lines: any("no allowed" in line for line in lines))
        self.assertEqual([line.strip() for line in lines if "no allowed" in line],
                         ["no allowed executor/reviewer pair"])
        self.assertEqual(marks(model(lines, "astra")), "○■■")
        record = menu.record()
        self.assertEqual((record["workers"], record["reviewers"]),
                         (["opus", "astra"], ["astra", "opus"]))
        menu.press(ESC)
        menu.leave()

    def test_a_seat_naming_a_removed_model_still_opens_c_with_the_efforts(self):
        menu = Menu(self)
        menu.screen()
        shipped = menu.config.read_text()
        cfg = tomllib.loads(shipped)
        del cfg["models"]["opus"]                         # removed while fix-api orchestrates on it
        menu.config.write_text(config.dump(cfg))
        lines = menu.press(b"c", title("config"))
        self.assertEqual(lines[2].split(), ["effort"])
        self.assertFalse(any(marks(line) for line in lines), lines)
        said = " ".join(line.strip() for line in lines)
        self.assertIn("fix-api's roles are not shown", said)
        self.assertIn("unknown model 'opus'", said)
        self.assertTrue(any("+ add a model" in line for line in lines), lines)
        menu.press(ESC)
        menu.config.write_text(shipped)                   # for the pick the child ends on
        menu.leave()

    def test_on_a_heading_only_the_efforts_show(self):
        menu = Menu(self)
        menu.screen()
        lines = menu.press(b"k", lambda lines: any("esc leave" in line for line in lines)
                           and "ACME" in highlighted(lines))
        lines = menu.press(b"c", title("config"))
        self.assertEqual(lines[2].split(), ["effort"])
        self.assertEqual(model(lines, "fable").split(), ["›", "fable", "claude", "‹", "xhigh",
                                                          "›", "▂▃▅▆█"])
        self.assertFalse(any(marks(line) for line in lines), lines)
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ effort   esc back")
        menu.press(ESC)
        menu.leave()

    def test_m_is_no_key(self):
        menu = Menu(self)
        lines = menu.screen()
        self.assertEqual(lines[-1].split("   ")[2:],
                         ["n new", "x stop", "c config", "i info", "s solo", "esc leave"])
        before = menu.record()
        mark = len(menu.text())
        os.write(menu.master, b"m")
        menu.press(b"k", lambda lines: any("esc leave" in line for line in lines)
                   and "ACME" in highlighted(lines))
        shown = terminal.ANSI.sub("", menu.text()[mark:])
        self.assertNotIn("agentkit · ", shown)            # no screen opened, no word said
        self.assertNotIn("not a key", shown)
        self.assertEqual(menu.record(), before)
        menu.leave()

    def test_an_open_menu_keeps_and_offers_a_creation_made_elsewhere(self):
        menu = Menu(self)
        menu.screen()
        menu.press(b"k", lambda lines: any("esc leave" in line for line in lines)
                   and "ACME" in highlighted(lines))
        menu.press(b"c", title("config"))
        # another process creates a seat while `c` is open, and writes what it was given
        menu.config.write_text(menu.config.read_text().replace(
            'orchestrator = "opus"\nworkers = ["opus", "astra"]',
            'orchestrator = "astra"\nworkers = ["fable"]\nreviewers = ["opus"]'))
        elsewhere = {"orchestrator": "astra", "workers": ["fable"], "reviewers": ["opus"]}
        self.assertEqual(menu.defaults(), elsewhere)
        menu.press(ENTER, lambda lines: "‹ max ›" in model(lines, "fable"))   # an effort saved
        self.assertEqual(tomllib.loads(menu.config.read_text())["models"]["fable"]["effort"],
                         "max")
        self.assertEqual(menu.defaults(), elsewhere)      # kept, whatever `c` read before
        menu.press(ESC)
        mark = len(menu.text())
        os.write(menu.master, b"n")
        menu.saw("Name: ", after=mark)
        os.write(menu.master, ENTER)
        lines = menu.picker(after=mark)
        rows = {line.lstrip("› ").split()[0]: marks(line) for line in lines if marks(line)}
        self.assertEqual((rows["Astra"], rows["Fable"], rows["Opus"]), ("●□□", "○■□", "○□■"))
        menu.press(ESC)
        menu.leave()

    def test_n_starts_from_what_the_last_session_was_created_with(self):
        menu = Menu(self)
        menu.screen()
        os.write(menu.master, b"n")
        menu.saw("Name: ")
        os.write(menu.master, ENTER)
        lines = menu.picker()
        self.assertIn("Opus 5.5", highlighted(lines))     # the shipped defaults, the first time
        self.assertEqual(marks(highlighted(lines)), "●■■")
        menu.press(DOWN + SPACE, lambda lines: "Astra" in highlighted(lines)
                   and marks(highlighted(lines)) == "●■■")
        menu.press(UP * 2 + RIGHT + SPACE, lambda lines: "Fable" in highlighted(lines)
                   and marks(highlighted(lines)) == "○■□")
        mark = len(menu.text())
        os.write(menu.master, ENTER)
        menu.saw("<opened new>", after=mark)
        record = menu.record("new")
        chosen = {"orchestrator": "astra", "workers": ["opus", "astra", "fable"],
                  "reviewers": ["opus", "astra"]}
        self.assertEqual({key: record[key] for key in chosen}, chosen)
        self.assertEqual(menu.defaults(), chosen)         # written by the creation
        menu.screen(after=mark)
        mark = len(menu.text())
        os.write(menu.master, b"n")
        menu.saw("Name: ", after=mark)
        os.write(menu.master, ENTER)
        lines = menu.picker(after=mark)
        self.assertIn("Astra", highlighted(lines))
        rows = {line.lstrip("› ").split()[0]: marks(line) for line in lines if marks(line)}
        self.assertEqual((rows["Astra"], rows["Fable"], rows["Opus"]), ("●■■", "○■□", "○■■"))
        menu.press(ESC)
        menu.leave()


if __name__ == "__main__":
    unittest.main(verbosity=2)

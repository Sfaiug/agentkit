"""`n` asks for a name, then shows selectors; Enter takes each default.

Each test runs `menu.loop` in a child process on a pty of its own, with the seat listing, the
usage rows, the meters and the probe faked, and the create step reduced to a line saying what
it was handed.  The dry run keeps all of those real, the tmux listing and the usage collection
too, over a usage cache every provider was asked for just now; only the launch and the
harness's command are faked.  No real tmux or adapter is asked anything -- a `tmux` on PATH
writes down each call, and the adapters are an empty directory -- and nothing starts a session;
the only process signalled is the test's own child.
"""

import fcntl
import json
import os
from pathlib import Path
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import terminal

CHILD = r"""
import json, os, sys
sys.path.insert(0, os.environ["SCREEN_REPO"])
from agentkit import config, menu, orch

def refused(*args, **kwargs):
    raise AssertionError("refused: nothing here launches")

def create(cfg, name, cwd, *args, selection=None, **kwargs):
    model, _, workers, reviewers = selection[1]
    config.save_session(cfg, name, model, workers, {"reviewers": reviewers})
    print(f"<created {name} {model} {','.join(workers)} {','.join(reviewers)}>", flush=True)
    return ["fake"]

def open_session(cfg, session, dry_run):
    print(f"<opened {session['name']}>", flush=True)

orch.launch = refused
orch.fresh_command = lambda cfg, name, seat=None, account=None: (["harness"], None)
dry_run = os.environ["SCREEN_DRY_RUN"] == "1"
if not dry_run:     # a dry run keeps the real listing, rows, probe, notices, create and open
    orch.sessions = lambda: []
    orch.held_names = lambda: set()
    menu.usage.collect = lambda cfg, **kwargs: json.loads(os.environ["SCREEN_PROVIDERS"])
    orch.job_notices = lambda: []
    orch.listing = lambda reconcile=True: []
    menu.usage_lines = lambda cfg, width: []
    menu.Live.probe = lambda self, now=None: False
    orch.create, menu.open_session = create, open_session
sys.exit(menu.loop(config.load(), dry_run=dry_run))
"""
RIGHT, LEFT = b"\x1b[C", b"\x1b[D"
DOWN, ENTER, ESC, SPACE = b"\x1b[B", b"\r", b"\x1b", b" "
SPENT = {"anthropic": {"meters": [{"name": "weekly_all", "used": 100, "exhausted": True,
                                   "resets_at": time.time() + 3 * 86400}]}}
# every provider at 100%, openai's week with no reset anybody knows
EVERYTHING_SPENT = {**{name: {"meters": [{"name": "weekly_all", "used": 100,
                                          "resets_at": time.time() + 86400}]}
                       for name in ("anthropic", "meta", "xai", "google", "mimo")},
                    "openai": {"meters": [{"name": "weekly_all", "used": 100}]}}


class Screen:
    """One child menu on a pty: what it wrote so far, and keys sent to it."""

    def __init__(self, case, providers=None, dry_run=False, rows=40, cols=100, models="", reviewers=None):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="new-session-screen-")
        case.addCleanup(home.cleanup)
        self.home = Path(home.name)
        self.tmux_calls = self.home / "tmux-calls"
        tmux = self.home / "bin" / "tmux"
        tmux.parent.mkdir()
        tmux.write_text(f'#!/bin/sh\necho "$*" >> {shlex.quote(str(self.tmux_calls))}\nexit 1\n')
        tmux.chmod(0o755)
        (self.home / "adapters").mkdir()
        (self.home / ".agentkit" / "state").mkdir(parents=True)
        text = (REPO / "config.default.toml").read_text() + "\n" + models
        if reviewers is not None:
            text = text.replace("\n[defaults]\n", "\n[defaults]\nreviewers = "
                                + json.dumps(reviewers) + "\n")
        (self.home / ".agentkit" / "config.toml").write_text(text)
        if dry_run:     # every provider asked just now, so neither a read nor a probe asks again
            now, state = time.time(), self.home / ".agentkit" / "state"
            for name in EVERYTHING_SPENT:
                (state / f"{name}-probe.lock").write_text(repr(now))
            (state / "usage.json").write_text(json.dumps({"fetched_at": now, "providers": {
                name: {"meters": [], **(providers or {}).get(name, {}), "resets": 0}
                for name in EVERYTHING_SPENT}}))
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in os.environ.items()
               if key not in ("NO_COLOR", "COLORTERM", "COLUMNS", "LINES", "TMUX")}
        env.update({"HOME": home.name, "PATH": f"{tmux.parent}:{os.environ['PATH']}",
                    "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AGENTKIT_ADAPTER_DIR": str(self.home / "adapters"),
                    "SCREEN_REPO": str(REPO), "SCREEN_PROVIDERS": json.dumps(providers or {}),
                    "SCREEN_DRY_RUN": "1" if dry_run else "0"})
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

    def saw(self, *texts):
        return self.until(lambda text: all(t in text for t in texts) and text, " & ".join(texts))

    def drawn(self, marker, where=None, after=0):
        """The lines of the last whole screen drawn with `marker` on it; row 1 first."""
        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written, or a frame printed once
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if any(marker in line for line in lines):
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, f"a screen with {marker!r}")

    def picker(self, where=None, after=0):
        # its heading, as its key line says what the pointer rests on after a click
        return self.drawn("orch  exec  review", where, after)

    def menu(self, after=0):
        return self.drawn("esc leave", after=after)

    def send(self, keys):
        os.write(self.master, keys)

    def leave(self):
        self.send(b"\x1b")
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


def highlighted(lines):
    return next(line for line in lines if line.startswith("›"))


def models(lines):
    return [line for line in lines if any(mark in line for mark in "●○■□")]


def marks(line):
    return "".join(char for char in line if char in "●○■□")


class NewSessionScreen(unittest.TestCase):
    def test_name_sits_in_the_content_column_above_the_keys_and_keeps_its_draft_on_resize(self):
        screen = Screen(self)
        screen.menu()
        screen.send(b"n")
        lines = screen.drawn("Name: auto")
        self.assertEqual(lines[2], "  Name: auto")
        self.assertEqual(lines[-2:], ["", "  esc back"])
        self.assertRegex(screen.text(), r"  Name: \x1b\[[0-9;]*mauto\x1b\[0m")
        screen.send(b"fix-api")
        screen.drawn("  Name: fix-api")
        mark = len(screen.text())
        fcntl.ioctl(screen.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 40, 0, 0))
        os.kill(screen.proc.pid, signal.SIGWINCH)
        lines = screen.drawn("  Name: fix-api", after=mark)
        self.assertEqual(lines[2], "  Name: fix-api")
        self.assertEqual(lines[-1], "  esc back")
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))
        mark = len(screen.text())
        row = len(lines)
        screen.send(f"\x1b[<0;3;{row}M\x1b[<0;3;{row}m".encode())
        screen.menu(after=mark)
        screen.leave()
        self.assertNotIn("<created", screen.text())

    def test_n_then_enter_starts_a_session_with_the_defaults(self):
        screen = Screen(self)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        lines = screen.picker()
        self.assertTrue(lines[0].startswith("agentkit · new session"), lines)
        self.assertIn("opus", highlighted(lines))                 # the cursor starts there
        self.assertEqual(lines[2].split(), ["orch", "exec", "review"])
        self.assertEqual(len(models(lines)), 7)
        self.assertEqual(marks(highlighted(lines)), "●■■")
        self.assertEqual([row.split()[0 if not row.startswith("›") else 1]
                          for row in models(lines) if marks(row)[1] == "■"], ["opus", "astra"])
        self.assertEqual([line for line in lines[3:-2]
                          if line and not line.startswith((" ", "›"))],
                         ["Claude", "ChatGPT", "Muse", "Grok", "Gemini", "MiMo"])
        self.assertTrue(lines[-1].startswith("  ↑↓←→ move   space choose   ⏎ start   esc back"))
        screen.send(ENTER)
        screen.saw("<created new opus opus,astra opus,astra>", "<opened new>")
        screen.menu(after=screen.text().index("<opened new>"))
        screen.leave()

    def test_down_and_space_change_the_orchestrator(self):
        screen = Screen(self)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        screen.picker()
        screen.send(DOWN)
        screen.picker(lambda lines: "astra" in highlighted(lines))
        screen.send(SPACE)
        lines = screen.picker(lambda lines: "astra" in highlighted(lines) and marks(highlighted(lines))[0] == "●")
        self.assertEqual([row for row in models(lines) if "●" in row],
                         [highlighted(lines)])                         # one choice, moved
        screen.send(ENTER)
        screen.saw("<created new astra opus,astra opus,astra>")
        screen.leave()

    def test_all_workers_may_be_toggled_off(self):
        screen = Screen(self)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        screen.picker()
        screen.send(RIGHT + SPACE)             # Opus's executor mark
        screen.picker(lambda lines: marks(highlighted(lines)) == "●□■")
        mark = len(screen.text())
        screen.send(DOWN + SPACE)              # Astra, the last executor, may go too
        lines = screen.picker(lambda lines: marks(highlighted(lines)) == "○□■",
                              after=mark)
        self.assertEqual(marks(next(line for line in lines if "opus" in line)), "●■■")
        # A click chooses Spark's executor mark even with the cursor in the orch column.
        screen.send(LEFT)
        row = next(number for number, line in enumerate(lines, 1) if "spark" in line)
        col = lines[2].index("exec") + 2
        screen.send(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode())
        screen.picker(lambda lines: "spark" in highlighted(lines)
                      and marks(highlighted(lines))[1] == "■")
        screen.send(ENTER)
        screen.saw("<created new opus spark opus,astra>")
        screen.leave()

    def test_a_spent_model_reads_dim_and_is_not_preselected(self):
        screen = Screen(self, providers=SPENT)
        screen.menu()
        mark = len(screen.text())
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        lines = screen.picker()
        opus = [row for row in lines if "opus" in row]
        self.assertEqual(len(opus), 1)
        self.assertEqual(marks(opus[0]), "○□□")
        self.assertIn("spent · resets", opus[0])
        self.assertRegex(screen.text()[mark:], r"\x1b\[[0-9;]*mopus")
        self.assertEqual(marks(highlighted(lines)), "●■■")
        # Astra reviewing itself could start, so Enter creates a self-review.
        screen.send(ENTER)
        screen.saw("<created new astra astra astra>")
        screen.leave()

    def test_with_everything_spent_nothing_is_chosen_and_enter_waits_for_a_choice(self):
        screen = Screen(self, providers=EVERYTHING_SPENT)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        lines = screen.picker()
        self.assertEqual([row for row in lines if "●" in row or "■" in row], [])
        # a week at 100% whose reset nobody knows is spent all the same, only with no time
        self.assertEqual(len([row for row in lines if "astra" in row and "spent" in row]), 1)
        screen.send(ENTER + SPACE + ENTER)     # Fable orchestrates; reviewer column wants a choice
        screen.send(DOWN * 2 + SPACE + ENTER)  # Astra reviews
        screen.saw("<created new fable  astra>")
        self.assertEqual(json.loads((screen.home / ".agentkit/state/session-new.json")
                                    .read_text())["workers"], [])
        screen.leave()
        self.assertEqual(screen.text().count("<created"), 1)

    def test_a_long_model_name_is_cut_and_every_line_fits_a_phone(self):
        long = "m" * 40
        screen = Screen(self, providers=SPENT, cols=40, models=f'[models.{long}]\nharness = "codex"\n'
                        'model = "x"\neffort = "xhigh"\nprovider = "openai"\n')
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        lines = screen.picker()
        self.assertEqual(len([line for line in lines if "mmmmmmmmmmmm…" in line]), 1)
        self.assertEqual([line for line in lines if terminal.cells(line) > 40], [])
        mark = len(screen.text())
        screen.send(ESC)
        screen.menu(after=mark)
        screen.leave()

    def test_esc_goes_back_and_creates_nothing(self):
        screen = Screen(self)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        screen.picker()
        mark = len(screen.text())
        screen.send(ESC)
        screen.menu(after=mark)
        screen.leave()
        self.assertNotIn("<created", screen.text())

    def test_the_dry_run_shows_the_same_screen_and_creates_no_session(self):
        screen = Screen(self, providers=SPENT, dry_run=True)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        lines = screen.picker()
        self.assertTrue(lines[0].startswith("agentkit · new session"), lines)
        self.assertIn("astra", highlighted(lines))
        self.assertEqual(marks(highlighted(lines)), "●■■")
        self.assertIn("spent · resets", "\n".join(lines))
        screen.send(RIGHT * 2 + DOWN + SPACE + ENTER)
        text = screen.saw("would attach new")
        screen.menu(after=text.index("would attach new"))
        screen.leave()
        self.assertEqual(list(screen.home.rglob("session-*.json")), [])
        calls = screen.tmux_calls.read_text().splitlines()
        self.assertTrue(calls)                      # the real listing asked, and only listed
        self.assertEqual([call for call in calls if "list-sessions" not in call.split()], [])
        self.assertIn("would start new: astra, workers astra", screen.text())
        self.assertNotIn("Traceback", screen.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)

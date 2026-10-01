"""`c` is a matrix of models moved through with the keys: a session's mark flipped is saved to
its record at once, there is always one orchestrator and one worker, an effort steps only within
its model's own list, a click flips a mark, and the rows under the models run their steps.
Without a session the matrix is the efforts alone.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, the way tests/test_close_and_info.py runs the menu, in a temporary HOME whose
config.toml is the shipped default plus a Haiku, for the seat `fix-api` whose record the child
writes first.  The harness catalog is faked -- Haiku takes only `none`, Opus low to max -- and
so are agentkit's build on the Version row, the Discord step itself, the meters, and the
orchestrator switch, which only writes the record; a harness's version is never asked.
Nothing here reads or writes the owner's ~/.agentkit, and the only process signalled is the
test's own child.
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
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import menu, terminal

# The child: the real screen, key reader and saver; fakes for the catalog, versions and steps.
CHILD = r"""
import json, os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, orch, terminal, update, usage

EFFORTS = {"claude-haiku-4-5": ["none"],
           "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"]}
config.catalog = lambda harness: [{"id": model, "label": model, "efforts": efforts}
                                  for model, efforts in EFFORTS.items() if harness == "claude"]
update.version = lambda harness: print("<harness version>", flush=True)
update.agentkit_version = lambda: "abc1234 · 2026-09-29"
menu.config_discord = lambda: print("<discord step>", flush=True)
session = os.environ["MATRIX_SESSION"] or None
if session:     # the seat whose roles the marks are, with no reviewers of its own
    config.save_session(config.load(), session, "opus", json.loads(os.environ["MATRIX_WORKERS"]),
                        {"cwd": "/", "created": 0})
usage.collect = lambda cfg, **kwargs: usage.Readings({})
orch.switch_orchestrator = lambda cfg, name, model, providers=None: (
    config.update_session(name, orchestrator=model), "")[1]
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard, session)
print("<left>", flush=True)
"""
HAIKU = """
[models.haiku]
harness = "claude"
model = "claude-haiku-4-5"
effort = "xhigh"
provider = "anthropic"
"""
ESC, UP, DOWN, RIGHT, LEFT, ENTER = b"\x1b", b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D", b"\r"
TAB = b"\t"
EFFORT_KEYS = "  ↑↓←→ move   ⏎ effort   esc back"   # the key line on an effort
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


class Screen:
    """One child `c` screen on a pty: what it wrote so far, keys sent to it, the file it saves;
    `env` over the child's own environment."""

    def __init__(self, case, workers=("opus", "astra"), rows=40, cols=100, child=CHILD, text=None,
                 session="fix-api", env=None):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="config-matrix-")
        case.addCleanup(home.cleanup)
        self.path = Path(home.name) / ".agentkit" / "config.toml"
        self.path.parent.mkdir()
        self.session = Path(home.name) / ".agentkit" / "state" / f"session-{session}.json"
        if text is None:
            text = (REPO / "config.default.toml").read_text() + HAIKU
        self.path.write_text(text)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        child_env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        child_env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                          "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                          "MATRIX_REPO": str(REPO), "MATRIX_SESSION": session or "",
                          "MATRIX_WORKERS": json.dumps(list(workers)), **(env or {})})
        self.proc = subprocess.Popen([sys.executable, "-c", child], stdin=self.slave,
                                     stdout=self.slave, stderr=self.slave, env=child_env,
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
        return self.until(lambda seen: text in seen[after:], text)

    def frame(self, where=None, after=0):
        """The lines of the last whole screen written over in place, as the screen shows them,
        row 1 first; the first one `where` accepts."""
        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if lines and "agentkit · config" in lines[0]:
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, "the config screen")

    def press(self, keys, where=None):
        """Keys, then the screen they drew."""
        mark = len(self.text())
        os.write(self.master, keys)
        return self.frame(where, after=mark)

    def click(self, col, row, where=None):
        """The left button down and up at `col`, `row`, as a terminal in mode 1006 reports it."""
        return self.press(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode(), where)

    def saved(self):
        return tomllib.loads(self.path.read_text())

    def record(self):
        return json.loads(self.session.read_text())

    def leave(self):
        mark = len(self.text())
        os.write(self.master, ESC)
        self.saw("<left>", after=mark)
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


def row(lines, name):
    """(the terminal row, the line) of `name`'s model row."""
    return next((number, line) for number, line in enumerate(lines, 1)
                if line[2:].split(" ")[0] == name)


def highlighted(lines):
    return next(line for line in lines if line.startswith("›"))


class Matrix(unittest.TestCase):
    def test_the_screen_is_the_models_under_their_providers_then_four_rows(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertTrue(lines[0].startswith("agentkit · config · fix-api "), lines[0])
        self.assertEqual(lines[2].split(), ["orch", "exec", "review", "effort"])
        body = "\n".join(lines)
        for heading in ("Claude", "ChatGPT", "Muse", "Grok", "Gemini", "MiMo"):
            self.assertIn(f"\n{heading}\n", body)
        self.assertEqual(row(lines, "fable")[1].split(), ["›", "fable", "claude", "○", "□", "□",
                                                          "‹", "xhigh", "›", "▂▃▅▆█"])
        self.assertEqual(row(lines, "opus")[1].split(), ["opus", "claude", "●", "■", "■",
                                                         "‹", "xhigh", "›", "▂▃▅▆█"])
        self.assertEqual(row(lines, "haiku")[0], row(lines, "opus")[0] + 1)   # under Claude
        tail = [line.strip() for line in lines]
        self.assertIn("+ add a model", tail)
        self.assertIn("Providers      Claude  ChatGPT  Muse  Grok  Gemini  MiMo  + add  − remove",
                      tail)
        self.assertTrue(any(line.startswith("Discord") and line.endswith("not connected")
                            for line in tail), tail)
        self.assertIn("Version        abc1234 · 2026-09-29", tail)
        self.assertEqual(tail[tail.index("Version        abc1234 · 2026-09-29") + 1:],
                         ["", "↑↓←→ move   ⏎ mark   esc back"])     # the last row
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ mark   esc back")
        screen.leave()
        self.assertIn("\x1b[?1049l", screen.text())       # the terminal given back
        self.assertNotIn("<harness version>", screen.text())

    def test_without_a_session_the_matrix_is_the_efforts_alone(self):
        screen = Screen(self, session=None)
        before = screen.path.read_bytes()
        lines = screen.frame()
        self.assertTrue(lines[0].startswith("agentkit · config "), lines[0])
        self.assertEqual(lines[2].split(), ["effort"])
        self.assertEqual(row(lines, "fable")[1].split(), ["›", "fable", "claude", "‹", "xhigh",
                                                          "›", "▂▃▅▆█"])
        self.assertEqual(lines[-1], EFFORT_KEYS)          # the effort is the first cell
        self.assertFalse(any(mark in line for line in lines for mark in "●○■□"), lines)
        lines = screen.press(LEFT, lambda lines: lines[-1] == "  ↑↓←→ move   ⏎ open   esc back")
        lines = screen.press(RIGHT + RIGHT, lambda lines: lines[-1] == EFFORT_KEYS)
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(DOWN + ENTER, lambda lines: "‹ max ›" in row(lines, "opus")[1])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "max")
        self.assertEqual(screen.saved()["defaults"], tomllib.loads(before.decode())["defaults"])
        screen.leave()

    def test_moving_to_a_worker_and_flipping_it_is_saved_to_the_record(self):
        screen = Screen(self)
        screen.frame()
        defaults = screen.saved()["defaults"]
        lines = screen.press(RIGHT + ENTER, lambda lines: "■" in row(lines, "fable")[1])
        self.assertEqual(screen.record()["workers"], ["opus", "astra", "fable"])
        lines = screen.press(DOWN + b" ", lambda lines: "□" in row(lines, "opus")[1])
        self.assertIn("opus", highlighted(lines))
        self.assertEqual(screen.record()["workers"], ["astra", "fable"])
        screen.leave()
        self.assertEqual(screen.record()["orchestrator"], "opus")
        self.assertEqual(screen.saved()["defaults"], defaults)    # no screen edits them

    def test_there_is_always_exactly_one_orchestrator(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertEqual("\n".join(lines).count("●"), 1)
        lines = screen.press(ENTER, lambda lines: "●" in row(lines, "fable")[1])
        self.assertEqual("\n".join(lines).count("●"), 1)
        self.assertEqual(screen.record()["orchestrator"], "fable")
        before = screen.session.read_bytes()
        lines = screen.press(b" ")                        # the one there is cannot be unmarked
        self.assertIn("●", row(lines, "fable")[1])
        self.assertEqual(screen.session.read_bytes(), before)
        lines = screen.press(DOWN * 3 + ENTER, lambda lines: "●" in row(lines, "astra")[1])
        self.assertEqual("\n".join(lines).count("●"), 1)
        self.assertEqual(screen.record()["orchestrator"], "astra")
        screen.leave()

    def test_the_last_worker_stays(self):
        screen = Screen(self, workers=["opus"])
        screen.frame()
        before = screen.session.read_bytes()
        lines = screen.press(DOWN + RIGHT + ENTER,
                             lambda lines: "exec needs one model" in lines[-3])
        self.assertIn("■", row(lines, "opus")[1])
        self.assertEqual(screen.session.read_bytes(), before)
        lines = screen.press(UP + ENTER, lambda lines: "■" in row(lines, "fable")[1])
        self.assertEqual(screen.record()["workers"], ["opus", "fable"])
        screen.press(DOWN + ENTER, lambda lines: "□" in row(lines, "opus")[1])   # now it can go
        self.assertEqual(screen.record()["workers"], ["fable"])
        screen.leave()

    def test_arrows_move_through_every_column_the_effort_s_too(self):
        screen = Screen(self)
        screen.frame()
        before = screen.path.read_bytes()
        # → through opus's role marks reaches its effort, and past it there is nothing
        lines = screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)
        self.assertIn("opus", highlighted(lines))
        lines = screen.press(RIGHT)
        self.assertEqual(lines[-1], EFFORT_KEYS)
        self.assertEqual(screen.path.read_bytes(), before)    # no arrow steps an effort
        # ← comes back to the reviewer mark, which Enter flips
        lines = screen.press(LEFT, lambda lines: lines[-1] == "  ↑↓←→ move   ⏎ mark   esc back")
        screen.press(ENTER, lambda lines: "□" in row(lines, "opus")[1])
        self.assertEqual(screen.record()["reviewers"], ["astra"])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "xhigh")
        screen.leave()

    def test_enter_steps_an_effort_up_and_round_from_its_highest(self):
        screen = Screen(self)
        screen.frame()
        effort = lambda: {name: model["effort"] for name, model in screen.saved()["models"].items()}
        # opus takes low to max: up from xhigh is max, and up from max is low again
        screen.press(DOWN + RIGHT * 3 + ENTER, lambda lines: "‹ max ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "max")
        screen.press(ENTER, lambda lines: "‹ low ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "low")
        screen.press(b" ", lambda lines: "‹ medium ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "medium")
        # haiku takes only none, its word alone: from xhigh it lands there, and none is all
        # there is
        screen.press(DOWN + ENTER, lambda lines: row(lines, "haiku")[1].endswith("  none"))
        self.assertEqual(effort()["haiku"], "none")
        before = screen.path.read_bytes()
        lines = screen.press(ENTER)
        self.assertTrue(row(lines, "haiku")[1].endswith("  none"), row(lines, "haiku")[1])
        self.assertEqual(screen.path.read_bytes(), before)
        self.assertEqual(effort()["fable"], "xhigh")
        screen.leave()

    def test_a_click_on_an_effort_s_left_arrow_steps_it_down(self):
        screen = Screen(self)
        lines = screen.frame()
        number, line = row(lines, "opus")
        lines = screen.click(line.index("‹") + 1, number,
                             lambda lines: "‹ high ›" in row(lines, "opus")[1])
        self.assertIn("opus", highlighted(lines))
        # the pointer rests on the effort it clicked: the key line says what that is
        self.assertEqual(lines[-1], "  " + terminal.TIPS["effort"].format(name="opus"))
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "high")
        screen.leave()

    def test_tab_changes_nothing(self):
        screen = Screen(self)
        screen.frame()
        before = screen.path.read_bytes()
        lines = screen.press(TAB)                         # on fable's orchestrator mark
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ mark   esc back")
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: "●" in row(lines, "fable")[1])   # still that mark
        screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)
        before = screen.path.read_bytes()
        lines = screen.press(TAB)                         # on opus's effort
        self.assertEqual(lines[-1], EFFORT_KEYS)
        self.assertIn("opus", highlighted(lines))
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: "‹ max ›" in row(lines, "opus")[1])  # still the effort
        screen.leave()

    def test_a_click_flips_a_mark(self):
        screen = Screen(self)
        lines = screen.frame()
        number, line = row(lines, "astra")
        lines = screen.click(line.index("■") + 1, number,
                             lambda lines: "□" in row(lines, "astra")[1])
        self.assertIn("astra", highlighted(lines))
        self.assertEqual(screen.record()["workers"], ["opus"])
        number, line = row(lines, "spark")
        lines = screen.click(line.index("○") + 1, number,
                             lambda lines: "●" in row(lines, "spark")[1])
        self.assertEqual(screen.record()["orchestrator"], "spark")
        number, line = row(lines, "opus")                 # a click on an effort's arrow steps it
        lines = screen.click(line.index("›", 2) + 1, number,
                             lambda lines: "‹ max ›" in row(lines, "opus")[1])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "max")
        column = EFFORT_KEYS.index("esc back") + 3      # and one on `esc back` leaves, where
                                                        # the effort's key line has it
        os.write(screen.master, f"\x1b[<0;{column};{len(lines)}M\x1b[<0;{column};{len(lines)}m"
                 .encode())
        screen.saw("<left>")
        self.assertEqual(screen.proc.wait(15), 0)

    def test_enter_on_discord_runs_its_step_and_on_version_nothing(self):
        screen = Screen(self)
        lines = screen.frame()
        # past every model, `+ add a model` and Providers
        models = lines[3:next(n for n, line in enumerate(lines) if "+ add a model" in line)]
        down = sum(1 for line in models if line.startswith(("  ", "›"))) + 2
        lines = screen.press(DOWN * down, lambda lines: highlighted(lines).startswith("› Discord"))
        self.assertEqual(lines[-1], "  ↑↓ move   ⏎ open   esc back")
        mark = len(screen.text())
        screen.press(ENTER)                               # the step, then the screen again
        screen.saw("<discord step>", after=mark)
        self.assertNotIn("\x1b[?1049l", screen.text()[mark:])   # typed on the matrix's keys
        lines = screen.press(DOWN, lambda lines: highlighted(lines).startswith("› Version"))
        self.assertEqual(lines[-1], "  ↑↓ move   esc back")      # no action to name
        mark = len(screen.text())
        lines = screen.press(ENTER)
        self.assertTrue(highlighted(lines).startswith("› Version"))
        self.assertNotIn("\x1b[?1049l", screen.text()[mark:])     # the terminal kept
        screen.leave()
        self.assertEqual(screen.text().count("<discord step>"), 1)

    def test_a_phone_draws_it_in_forty_columns(self):
        screen = Screen(self, workers=["opus"], rows=24, cols=40)
        lines = screen.frame()
        self.assertLessEqual(len(lines), 23)
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(lines[2].split(), ["orch", "exec", "review", "effort"])
        self.assertIn("add a model", "\n".join(lines))
        # what a key could not do has lines of its own, however little room the rows leave
        lines = screen.press(DOWN + RIGHT + ENTER,
                             lambda lines: "exec needs" in "\n".join(lines))
        self.assertLessEqual(len(lines), 23)
        self.assertIn("opus", highlighted(lines))
        lines = screen.press(DOWN * 10, lambda lines: highlighted(lines).startswith("› Version"))
        self.assertLessEqual(len(lines), 23)
        self.assertNotIn("exec needs", "\n".join(lines))   # until the next key
        screen.leave()


if __name__ == "__main__":
    unittest.main()

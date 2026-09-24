"""`c` is a matrix of models moved through with the keys: a mark flipped is saved at once, there
is always one orchestrator and one worker, an effort steps only within its model's own list, a
click flips a mark, and the rows under the models run their steps.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, the way tests/test_close_and_info.py runs the menu, in a temporary HOME whose
config.toml is the shipped default plus a Haiku.  The harness catalog is faked -- Haiku takes
only `none`, Opus low to max -- and so are the versions on the Update row and the Discord and
Update steps themselves.  Nothing here reads or writes the owner's ~/.agentkit, and the only
process signalled is the test's own child.
"""

import fcntl
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
from agentkit import terminal

# The child: the real screen, key reader and saver; fakes for the catalog, versions and steps.
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, terminal, update

EFFORTS = {"claude-haiku-4-5": ["none"],
           "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"]}
config.catalog = lambda harness: [{"id": model, "label": model, "efforts": efforts}
                                  for model, efforts in EFFORTS.items() if harness == "claude"]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
menu.config_discord = lambda: print("<discord step>", flush=True)
menu.config_update = lambda cfg: print("<update step>", flush=True)
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
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
    """One child `c` screen on a pty: what it wrote so far, keys sent to it, the file it saves."""

    def __init__(self, case, workers=None, rows=40, cols=100, child=CHILD, text=None):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="config-matrix-")
        case.addCleanup(home.cleanup)
        self.path = Path(home.name) / ".agentkit" / "config.toml"
        self.path.parent.mkdir()
        if text is None:
            text = (REPO / "config.default.toml").read_text() + HAIKU
        if workers is not None:
            text = text.replace('workers = ["opus", "astra"]', f"workers = {workers!r}"
                                .replace("'", '"'))
        self.path.write_text(text)
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "MATRIX_REPO": str(REPO)})
        self.proc = subprocess.Popen([sys.executable, "-c", child], stdin=self.slave,
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

    def leave(self):
        mark = len(self.text())
        os.write(self.master, b"q")
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
        self.assertEqual(lines[2].split(), ["orchestrator", "worker", "effort"])
        body = "\n".join(lines)
        for heading in ("Claude", "ChatGPT", "Muse", "Grok", "Gemini", "MiMo"):
            self.assertIn(f"\n{heading}\n", body)
        self.assertEqual(row(lines, "fable")[1].split(), ["›", "fable", "claude", "○", "□",
                                                          "‹", "xhigh", "›"])
        self.assertEqual(row(lines, "opus")[1].split(), ["opus", "claude", "●", "■",
                                                         "‹", "xhigh", "›"])
        self.assertEqual(row(lines, "haiku")[0], row(lines, "opus")[0] + 1)   # under Claude
        tail = [line.strip() for line in lines]
        self.assertIn("+ add a model", tail)
        self.assertIn("Providers      Claude  ChatGPT  Muse  Grok  Gemini  MiMo  + add  − remove",
                      tail)
        self.assertTrue(any(line.startswith("Discord") and line.endswith("not connected")
                            for line in tail), tail)
        self.assertTrue(any(line.startswith("Update") and "abc1234 · up to date" in line
                            for line in tail), tail)
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ mark   esc back")
        screen.leave()
        self.assertIn("\x1b[?1049l", screen.text())       # the terminal given back

    def test_moving_to_a_default_worker_and_flipping_it_is_saved(self):
        screen = Screen(self)
        screen.frame()
        lines = screen.press(RIGHT + ENTER, lambda lines: "■" in row(lines, "fable")[1])
        self.assertEqual(screen.saved()["defaults"]["workers"], ["opus", "astra", "fable"])
        lines = screen.press(DOWN + b" ", lambda lines: "□" in row(lines, "opus")[1])
        self.assertIn("opus", highlighted(lines))
        self.assertEqual(screen.saved()["defaults"]["workers"], ["astra", "fable"])
        screen.leave()
        self.assertEqual(screen.saved()["defaults"]["orchestrator"], "opus")

    def test_there_is_always_exactly_one_orchestrator(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertEqual("\n".join(lines).count("●"), 1)
        lines = screen.press(ENTER, lambda lines: "●" in row(lines, "fable")[1])
        self.assertEqual("\n".join(lines).count("●"), 1)
        self.assertEqual(screen.saved()["defaults"]["orchestrator"], "fable")
        before = screen.path.read_bytes()
        lines = screen.press(b" ")                        # the one there is cannot be unmarked
        self.assertIn("●", row(lines, "fable")[1])
        self.assertEqual(screen.path.read_bytes(), before)
        lines = screen.press(DOWN * 3 + ENTER, lambda lines: "●" in row(lines, "astra")[1])
        self.assertEqual("\n".join(lines).count("●"), 1)
        self.assertEqual(screen.saved()["defaults"]["orchestrator"], "astra")
        screen.leave()

    def test_the_last_worker_stays(self):
        screen = Screen(self, workers=["opus"])
        screen.frame()
        before = screen.path.read_bytes()
        lines = screen.press(DOWN + RIGHT + ENTER,
                             lambda lines: "the default workers need one model" in lines[-3])
        self.assertIn("■", row(lines, "opus")[1])
        self.assertEqual(screen.path.read_bytes(), before)
        lines = screen.press(UP + ENTER, lambda lines: "■" in row(lines, "fable")[1])
        self.assertEqual(screen.saved()["defaults"]["workers"], ["opus", "fable"])
        screen.press(DOWN + ENTER, lambda lines: "□" in row(lines, "opus")[1])   # now it can go
        self.assertEqual(screen.saved()["defaults"]["workers"], ["fable"])
        screen.leave()

    def test_arrows_move_through_every_column_the_effort_s_too(self):
        screen = Screen(self)
        screen.frame()
        before = screen.path.read_bytes()
        # → from opus's worker mark reaches its effort, and past it there is nothing
        lines = screen.press(DOWN + RIGHT + RIGHT, lambda lines: lines[-1] == EFFORT_KEYS)
        self.assertIn("opus", highlighted(lines))
        lines = screen.press(RIGHT)
        self.assertEqual(lines[-1], EFFORT_KEYS)
        self.assertEqual(screen.path.read_bytes(), before)    # no arrow steps an effort
        # ← comes back to the worker mark, which Enter flips
        lines = screen.press(LEFT, lambda lines: lines[-1] == "  ↑↓←→ move   ⏎ mark   esc back")
        screen.press(ENTER, lambda lines: "□" in row(lines, "opus")[1])
        self.assertEqual(screen.saved()["defaults"]["workers"], ["astra"])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "xhigh")
        screen.leave()

    def test_enter_steps_an_effort_up_and_round_from_its_highest(self):
        screen = Screen(self)
        screen.frame()
        effort = lambda: {name: model["effort"] for name, model in screen.saved()["models"].items()}
        # opus takes low to max: up from xhigh is max, and up from max is low again
        screen.press(DOWN + RIGHT + RIGHT + ENTER, lambda lines: "‹ max ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "max")
        screen.press(ENTER, lambda lines: "‹ low ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "low")
        screen.press(b" ", lambda lines: "‹ medium ›" in row(lines, "opus")[1])
        self.assertEqual(effort()["opus"], "medium")
        # haiku takes only none: from xhigh it lands there, and none is all there is
        screen.press(DOWN + ENTER, lambda lines: "‹ none ›" in row(lines, "haiku")[1])
        self.assertEqual(effort()["haiku"], "none")
        before = screen.path.read_bytes()
        lines = screen.press(ENTER)
        self.assertIn("‹ none ›", row(lines, "haiku")[1])
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
        self.assertEqual(lines[-1], EFFORT_KEYS)
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
        screen.press(DOWN + RIGHT + RIGHT, lambda lines: lines[-1] == EFFORT_KEYS)
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
        self.assertEqual(screen.saved()["defaults"]["workers"], ["opus"])
        number, line = row(lines, "spark")
        lines = screen.click(line.index("○") + 1, number,
                             lambda lines: "●" in row(lines, "spark")[1])
        self.assertEqual(screen.saved()["defaults"]["orchestrator"], "spark")
        number, line = row(lines, "opus")                 # a click on an effort's arrow steps it
        lines = screen.click(line.index("›", 2) + 1, number,
                             lambda lines: "‹ max ›" in row(lines, "opus")[1])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "max")
        column = lines[-1].index("esc back") + 3            # and one on `esc back` leaves
        os.write(screen.master, f"\x1b[<0;{column};{len(lines)}M\x1b[<0;{column};{len(lines)}m"
                 .encode())
        screen.saw("<left>")
        self.assertEqual(screen.proc.wait(15), 0)

    def test_enter_on_discord_or_update_runs_its_step(self):
        screen = Screen(self)
        lines = screen.frame()
        # past every model, `+ add a model` and Providers
        down = sum(1 for line in lines if line.startswith(("  ", "›")) and "‹" in line) + 2
        lines = screen.press(DOWN * down, lambda lines: highlighted(lines).startswith("› Discord"))
        self.assertEqual(lines[-1], "  ↑↓ move   ⏎ open   esc back")
        mark = len(screen.text())
        screen.press(ENTER)                               # the step, then the screen again
        screen.saw("<discord step>", after=mark)
        self.assertIn("\x1b[?1049l", screen.text()[mark:])    # it had the terminal as it was
        self.assertNotIn("<update step>", screen.text())
        lines = screen.press(DOWN, lambda lines: highlighted(lines).startswith("› Update"))
        mark = len(screen.text())
        screen.press(ENTER)
        screen.saw("<update step>", after=mark)
        screen.leave()
        self.assertEqual(screen.text().count("<discord step>"), 1)
        self.assertEqual(screen.text().count("<update step>"), 1)

    def test_a_phone_draws_it_in_forty_columns(self):
        screen = Screen(self, workers=["opus"], rows=24, cols=40)
        lines = screen.frame()
        self.assertLessEqual(len(lines), 23)
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(lines[2].split(), ["orch", "work", "effort"])
        self.assertIn("add a model", "\n".join(lines))
        # what a key could not do has lines of its own, however little room the rows leave
        lines = screen.press(DOWN + RIGHT + ENTER,
                             lambda lines: "the default workers need" in "\n".join(lines))
        self.assertLessEqual(len(lines), 23)
        self.assertIn("opus", highlighted(lines))
        lines = screen.press(DOWN * 10, lambda lines: highlighted(lines).startswith("› Update"))
        self.assertLessEqual(len(lines), 23)
        self.assertNotIn("the default workers need", "\n".join(lines))   # until the next key
        screen.leave()


if __name__ == "__main__":
    unittest.main()

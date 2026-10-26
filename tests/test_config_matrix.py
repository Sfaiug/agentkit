"""`c` is a matrix of models moved through with the keys: a session's mark flipped is saved to
its record at once, there is always one orchestrator and one reviewer, an effort steps only within
its model's own list, a click flips a mark, and the rows under the models run their steps.
Without a session the matrix is the efforts alone.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, the way tests/test_close_and_info.py runs the menu, in a temporary HOME whose
config.toml is the shipped default plus a Haiku, for the seat `fix-api` whose record the child
writes first.  The harness catalog is faked -- Haiku takes only `none`, Opus low to max -- and
so are agentkit's build under the rows, the Discord step itself, the meters, and the
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
from unittest import mock

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
orch.switch_orchestrator = lambda cfg, name, model, providers=None, **_kw: (
    config.update_session(name, orchestrator=model), "")[1]
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard, session)
print("<left>", flush=True)
"""
# Run before every child's own code: each page as drawn from its first frame, so the frame read
# after a key is the page it drew, not the menu's next idle redraw (test_page_comes_up.py's).
FADELESS = """
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from agentkit import motion
motion.FADE = 0
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
KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   esc back"   # wherever the highlight is
PAGE_KEYS = "  ↑↓←→ move   ⏎ choose   esc back"   # the pages under it, with no `r`
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLORTERM", "COLUMNS", "LINES")


class Lines(list):
    """A drawn screen's lines as they show, and `lit`: (the line, its text) of the cell the keys
    reverse, or None: the one place the screen says which cell is at hand."""
    lit = None


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
        self.proc = subprocess.Popen([sys.executable, "-c", FADELESS + child], stdin=self.slave,
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
                raw = part.split("\x1b[J")[0].split("\n")[:-1]
                lines = Lines(terminal.ANSI.sub("", line).rstrip("\r") for line in raw)
                lines.lit = next(((number, line.split("\x1b[7m")[1].split("\x1b[")[0].strip())
                                  for number, line in enumerate(raw) if "\x1b[7m" in line), None)
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

    def effort(self, name):
        """`name`'s effort as the seat's record holds it, where a step on its `c` is saved."""
        return self.record()["efforts"][name]["effort"]

    def leave(self):
        mark = len(self.text())
        os.write(self.master, ESC)
        self.saw("<left>", after=mark)
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


# Each model by the full name its row shows (config.model_name), the shipped catalog's labels.
FULL = {"fable": "Fable 5.1", "opus": "Opus 5.5", "haiku": "Haiku 4.5", "astra": "GPT-6-Astra",
        "spark": "muse-spark-1.3-contributor", "grok": "Grok 4.7", "gemini": "Gemini 3.8 Flash",
        "mimo": "MiMo V2.6 Pro"}


def row(lines, name):
    """(the terminal row, the line) of `name`'s model row, drawn by its full name -- cut, `…`
    last, where the screen is narrow."""
    def drawn(line):
        label = line[2:].split("  ")[0]
        return label == FULL[name] or label.endswith("…") and FULL[name].startswith(label[:-1])
    return next((number, line) for number, line in enumerate(lines, 1) if drawn(line))


def effort(lines, name):
    """The first effort `name`'s model row shows, beside its first marked role: its word."""
    return next(word for word in row(lines, name)[1].split() if word in menu.EFFORT_RANK)


def lit(lines, name):
    """The text of the cell the keys reverse on `name`'s model row, or None."""
    return lines.lit[1] if lines.lit and lines.lit[0] + 1 == row(lines, name)[0] else None


def on_effort(lines, name):
    """Whether the keys' highlight is on `name`'s effort: its word reversed."""
    return lit(lines, name) in menu.EFFORT_RANK


def on_mark(lines, name):
    """Whether the keys' highlight is on one of `name`'s role marks."""
    return lit(lines, name) in ("●", "■", "□", "○")


def highlighted(lines):
    return next(line for line in lines if line.startswith("›"))


def headings(lines):
    """Where the column headings are: under the meters, over the models."""
    return next(number for number, line in enumerate(lines) if line.split()[:1] == ["orch"])


class Matrix(unittest.TestCase):
    def test_the_screen_is_the_models_under_their_providers_then_four_rows(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertTrue(lines[0].startswith("agentkit · config "), lines[0])
        # whom the marks are for, over their headings: the seat it was opened on
        self.assertEqual(lines[headings(lines) - 1].split(), ["For", "fix-api"])
        self.assertEqual(lines[headings(lines)].split(), ["orch", "builds", "reviews"])
        # each subscription's meter over the models, as on the main screen, once
        meters = " ".join(" ".join(lines[2:headings(lines) - 1]).split())
        for name in ("Claude", "ChatGPT", "Muse", "Grok", "Gemini", "MiMo"):
            self.assertEqual(meters.count(f"{name} — no reading yet"), 1, meters)
        self.assertEqual(lines[headings(lines) - 2], "")
        body = "\n".join(lines)
        for heading in ("Claude Code", "Codex", "Muse Code", "Grok Build", "Antigravity",
                        "OpenCode"):           # each model under its harness
            self.assertIn(f"\n{heading}\n", body)
        self.assertEqual(row(lines, "fable")[1].split(), ["›", "Fable", "5.1", "○", "□", "□"])
        self.assertEqual(row(lines, "opus")[1].split(), ["Opus", "5.5", *("●", "▰▰▰▰▱", "xhigh"),
                                                         *("■", "▰▰▰▰▱", "xhigh") * 2])
        self.assertEqual(row(lines, "haiku")[0], row(lines, "opus")[0] + 1)   # under Claude
        tail = [line.strip() for line in lines]
        self.assertIn("Models", tail)
        self.assertIn("Subscriptions", tail)          # each subscription is its meter, above
        self.assertTrue(any(line.startswith("Discord") and line.endswith("not connected")
                            for line in tail), tail)
        # the build under the last row, nothing said of the highlighted model
        version = tail.index("Version abc1234 · 2026-09-29")
        self.assertTrue(tail[version - 2].startswith("Weekly audit"), tail)
        self.assertEqual(tail[version - 1:], ["", "Version abc1234 · 2026-09-29", "",
                                              KEYS.strip()])
        self.assertEqual(lines[-1], KEYS)
        screen.leave()
        self.assertIn("\x1b[?1049l", screen.text())       # the terminal given back
        self.assertNotIn("<harness version>", screen.text())

    def test_without_a_session_the_marks_are_new_seats(self):
        screen = Screen(self, session=None)
        before = screen.path.read_bytes()
        lines = screen.frame()
        self.assertTrue(lines[0].startswith("agentkit · config "), lines[0])
        self.assertEqual(lines[headings(lines) - 1].split(), ["For", "new", "seats"])
        self.assertEqual(row(lines, "opus")[1].split()[2::3], ["●", "■", "■"])
        self.assertEqual(lines[-1], KEYS)
        lines = screen.press(DOWN + RIGHT, lambda lines: on_effort(lines, "opus"))
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: effort(lines, "opus") == "max")
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
        self.assertIn("Opus 5.5", highlighted(lines))
        self.assertEqual(screen.record()["workers"], ["astra", "fable"])
        screen.leave()
        self.assertEqual(screen.record()["orchestrator"], "opus")
        self.assertEqual(screen.saved()["defaults"], defaults)    # no screen edits them

    def test_there_is_always_exactly_one_orchestrator(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertEqual("\n".join(lines).count("●"), 1)
        # another model's mark moves the seat (the switch, its question with it, faked)
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

    def test_the_last_worker_may_go_and_the_orchestrator_builds(self):
        screen = Screen(self, workers=["opus"])
        screen.frame()
        lines = screen.press(DOWN + RIGHT * 2 + ENTER, lambda lines: screen.record()["workers"] == [])
        self.assertIn("■", row(lines, "opus")[1])     # the orchestrator's own mark: it builds
        self.assertEqual(screen.record()["reviewers"], ["opus"])
        lines = screen.press(UP + ENTER, lambda lines: "■" in row(lines, "fable")[1])
        self.assertEqual(screen.record()["workers"], ["fable"])
        lines = screen.press(DOWN, lambda lines: "□" in row(lines, "opus")[1])
        screen.leave()

    def test_arrows_move_through_every_column_the_effort_s_too(self):
        screen = Screen(self)
        screen.frame()
        before = screen.session.read_bytes()
        # → through opus's marks and the efforts beside them reaches its last, and past it nothing
        lines = screen.press(DOWN + RIGHT * 5, lambda lines: on_effort(lines, "opus"))
        self.assertIn("Opus 5.5", highlighted(lines))
        lines = screen.press(RIGHT)
        self.assertTrue(on_effort(lines, "opus"), lines.lit)
        self.assertEqual(screen.session.read_bytes(), before)    # no arrow steps an effort
        # ← comes back to the reviewer mark, which Enter flips
        lines = screen.press(LEFT, lambda lines: on_mark(lines, "opus"))
        screen.press(ENTER, lambda lines: "□" in row(lines, "opus")[1])
        self.assertEqual(screen.record()["reviewers"], ["astra"])
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "xhigh")
        screen.leave()

    def test_enter_steps_an_effort_up_and_round_from_its_highest(self):
        screen = Screen(self, workers=["opus", "haiku"])
        screen.frame()
        given = screen.path.read_bytes()
        efforts = lambda: {name: model["effort"] for name, model in screen.record()["efforts"].items()}
        # opus takes low to max: up from xhigh is max, and up from max is low again
        screen.press(DOWN + RIGHT + ENTER, lambda lines: effort(lines, "opus") == "max")
        self.assertEqual(efforts()["opus"], "max")
        screen.press(ENTER, lambda lines: effort(lines, "opus") == "low")
        self.assertEqual(efforts()["opus"], "low")
        screen.press(b" ", lambda lines: effort(lines, "opus") == "medium")
        self.assertEqual(efforts()["opus"], "medium")
        # haiku takes only none, its word alone: from xhigh its build effort lands there, and
        # none is all there is
        built = lambda lines: row(lines, "haiku")[1].split()[-4:-2] == ["■", "none"]
        screen.press(DOWN + RIGHT * 2 + ENTER, built)
        self.assertEqual(screen.record()["efforts"]["haiku"]["exec_effort"], "none")
        before = screen.session.read_bytes()
        lines = screen.press(ENTER)
        self.assertTrue(built(lines), row(lines, "haiku")[1])
        self.assertEqual(screen.session.read_bytes(), before)
        self.assertEqual(efforts()["opus"], "medium")      # no other model stepped
        self.assertEqual(screen.path.read_bytes(), given)     # the seat's, not new seats'
        screen.leave()

    def test_a_click_on_an_effort_s_cell_takes_that_level(self):
        screen = Screen(self)
        lines = screen.frame()
        number, line = row(lines, "opus")                 # low, medium, high: its third
        lines = screen.click(line.index("▰") + 3, number,
                             lambda lines: effort(lines, "opus") == "high")
        self.assertIn("Opus 5.5", highlighted(lines))
        self.assertEqual(screen.effort("opus"), "high")
        screen.leave()

    def test_tab_changes_nothing(self):
        screen = Screen(self)
        screen.frame()
        before = screen.path.read_bytes()
        lines = screen.press(TAB)                         # on fable's orchestrator mark
        self.assertEqual(lines[-1], KEYS)
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER,                               # still that mark: it moves the seat
                     lambda lines: "●" in row(lines, "fable")[1])
        screen.press(DOWN + RIGHT * 2, lambda lines: on_effort(lines, "opus"))  # its build's
        before = screen.path.read_bytes()
        lines = screen.press(TAB)                         # on opus's effort
        self.assertTrue(on_effort(lines, "opus"), lines.lit)
        self.assertIn("Opus 5.5", highlighted(lines))
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: effort(lines, "opus") == "max")  # still the effort
        screen.leave()

    def test_a_click_flips_a_mark(self):
        screen = Screen(self)
        lines = screen.frame()
        number, line = row(lines, "astra")
        lines = screen.click(line.index("■") + 1, number,
                             lambda lines: "□" in row(lines, "astra")[1])
        self.assertIn("GPT-6-Astra", highlighted(lines))
        self.assertEqual(screen.record()["workers"], ["opus"])
        number, line = row(lines, "spark")
        lines = screen.click(line.index("○") + 1, number,  # moves the seat, as the key does
                             lambda lines: "●" in row(lines, "spark")[1])
        self.assertEqual(screen.record()["orchestrator"], "spark")
        number, line = row(lines, "opus")      # a click on an effort's word steps it, its build's
        lines = screen.click(line.index("xhigh") + 1, number,
                             lambda lines: effort(lines, "opus") == "max")
        self.assertEqual(screen.record()["efforts"]["opus"]["exec_effort"], "max")
        column = KEYS.index("esc back") + 3      # and one on `esc back` leaves
        os.write(screen.master, f"\x1b[<0;{column};{len(lines)}M\x1b[<0;{column};{len(lines)}m"
                 .encode())
        screen.saw("<left>")
        self.assertEqual(screen.proc.wait(15), 0)

    def test_enter_on_discord_runs_its_step_and_version_is_no_stop(self):
        screen = Screen(self)
        lines = screen.frame()
        # past every model, `Models` and `Subscriptions`
        models = lines[headings(lines) + 1:next(n for n, line in enumerate(lines)
                                                if line.strip() == "Models")]
        down = sum(1 for line in models if line.startswith(("  ", "›"))) + 2
        lines = screen.press(DOWN * down, lambda lines: highlighted(lines).startswith("› Discord"))
        self.assertEqual(lines[-1], KEYS)
        mark = len(screen.text())
        screen.press(ENTER)                               # the step, then the screen again
        screen.saw("<discord step>", after=mark)
        self.assertNotIn("\x1b[?1049l", screen.text()[mark:])   # typed on the matrix's keys
        lines = screen.press(DOWN, lambda lines: highlighted(lines).startswith("› Weekly audit"))
        self.assertEqual(lines[-1], KEYS)   # its step, like Discord's
        # the last stop: the build under the page is read, and never highlighted
        lines = screen.press(DOWN, lambda lines: highlighted(lines).startswith("› Weekly audit"))
        self.assertIn("Version abc1234 · 2026-09-29", [line.strip() for line in lines])
        screen.leave()
        self.assertEqual(screen.text().count("<discord step>"), 1)

    def test_a_phone_draws_it_in_forty_columns(self):
        screen = Screen(self, workers=["opus"], rows=24, cols=40)
        lines = screen.frame()
        self.assertLessEqual(len(lines), 23)
        self.assertIn("Version abc1234 · 2026-09-29", [line.strip() for line in lines])      # on the first page
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(lines[headings(lines)].split(), ["orch", "builds", "reviews"])
        # what a key could not do has lines of its own, however little room the rows leave
        lines = screen.press(DOWN + RIGHT * 4 + ENTER,
                             lambda lines: "at least one model reviews" in "\n".join(lines))
        self.assertLessEqual(len(lines), 23)
        self.assertTrue(highlighted(lines).startswith("› Opus"), lines)     # cut, on a phone
        lines = screen.press(DOWN * 11,
                             lambda lines: highlighted(lines).startswith("› Weekly audit"))
        self.assertLessEqual(len(lines), 23)
        self.assertIn("Version abc1234 · 2026-09-29", [line.strip() for line in lines])      # and on the last
        self.assertNotIn("at least one model reviews", "\n".join(lines))   # until the next key
        # Wait for selection: the row is already visible on the first Up redraw.
        lines = screen.press(UP * 3, lambda lines: highlighted(lines) == "› Models")
        self.assertEqual(highlighted(lines), "› Models")
        self.assertLessEqual(len(lines), 23)
        screen.leave()

    def test_a_short_screen_leads_its_page_with_the_meters(self):
        # over the page, six meters on 40 by 12 would leave it fewer than LEAST rows
        for rows in (12, 16):
            screen = Screen(self, workers=["opus"], rows=rows, cols=40)
            lines = screen.frame()
            self.assertLessEqual(len(lines), rows, lines)
            self.assertTrue(highlighted(lines).startswith("› Fable"), lines)
            self.assertTrue(lines[-1].endswith("esc back"), lines)
            screen.leave()
        self.assertIn("Claude Code", lines)               # the harness over the highlight

    def test_a_short_screen_s_page_holds_the_meter_the_highlight_is_on(self):
        # folded into the page, a meter is one cell of several on its line (terminal.under)
        places = {5: (None, [(3, 35, ("usage", 6), ("usage", 6))]), 9: (("model", "fable"), [])}
        with mock.patch.object(terminal, "height", return_value=8):
            top, room = menu.matrix_page([""] * 10, places, ("usage", 6), 9, [], "")
        self.assertLessEqual(top, 5)
        self.assertLess(5, top + room)


if __name__ == "__main__":
    unittest.main()

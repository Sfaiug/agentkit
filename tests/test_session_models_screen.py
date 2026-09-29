"""`m` on a session opens its orchestrator, executors and reviewers with its current
models chosen: a role flip saves to the session's record at once, each group keeps one
model, and a choice leaving no allowed pair is refused in one line.

The offline tests flip `menu.session_mark` against session records in a throwaway HOME and
prove the run boundary: a run launched next reads the new groups, one already going keeps
the groups its receipt saved. The screen tests run `menu.loop` in a child process on a pty
of its own, the way tests/test_close_and_info.py does, with the seat listing, each seat's
word, the usage rows, the probe and the orchestrator switch faked; the session records
are real files in the child's temporary HOME, and the flips land in them. Nothing here
starts a seat or a tmux server, and the only process signalled is the test's own child.
"""

from contextlib import redirect_stdout
import fcntl
import io
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
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from test_v4n import Sandbox
from agentkit import config, menu, run, terminal, usage

# The child: the real loop, draw, key reader and models screen; fakes for what a seat is,
# what it is doing and what opening does. The session records are real, written before
# the loop starts: fix-api holds both groups, other-seat a legacy workers-only one.
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MODELS_REPO"])
from agentkit import config, menu, orch, usage

cfg = config.load()
down = usage.Readings({})
down.harnesses = {"claude": "claude is not logged in"}
config.save_session(cfg, "fix-api", "opus", ["opus", "astra"],
                    {"reviewers": ["astra"], "cwd": "/", "created": 0})
config.save_session(cfg, "other-seat", "astra", ["astra"], {"cwd": "/", "created": 0})
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": None, "path": "/", "created": 0}
    for name in ("fix-api", "other-seat")]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "",
                                                     "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: down
orch.switch_orchestrator = lambda cfg, name, model, providers=None, log=print: (
    config.update_session(name, orchestrator=model), "")[1]
menu.open_session = lambda cfg, session, dry_run: print(f"<opened {session['name']}>",
                                                        flush=True)
sys.exit(menu.loop(cfg, dry_run=False))
"""
ESC, DOWN, RIGHT, LEFT, ENTER, SPACE = b"\x1b", b"\x1b[B", b"\x1b[C", b"\x1b[D", b"\r", b" "
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


def marks(line):
    return "".join(char for char in terminal.plain(line) if char in "●○■□")


class Screen:
    """One child menu on a pty: what it wrote so far, keys and clicks sent to it, and the
    temporary HOME whose session records its flips save."""

    def __init__(self, case, rows=30, cols=100):
        self.case = case
        home = tempfile.TemporaryDirectory(prefix="session-models-")
        case.addCleanup(home.cleanup)
        self.home = Path(home.name)
        (self.home / ".agentkit").mkdir()
        (self.home / ".agentkit" / "config.toml").write_text(
            (REPO / "config.default.toml").read_text())
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "MODELS_REPO": str(REPO)})
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

    def send(self, keys):
        os.write(self.master, keys)

    def mark(self):
        return len(self.text())

    def frame(self, where=None, keys="q leave", after=0):
        """The lines of the last whole screen written over in place whose key line says
        `keys` (the menu's own by default), as the screen shows them; row 1 first."""
        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue                  # still being written
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if any(keys in line for line in lines):
                    return lines if where is None or where(lines) else None
            return None
        return self.until(ready, f"a screen ending {keys!r}")

    def models(self, seat, where=None, after=0):
        return self.frame(lambda lines: lines[0].startswith(f"agentkit · {seat} models")
                          and (where is None or where(lines)), "esc back", after)

    def highlighted(self, lines):
        marked = [line for line in lines if line.startswith("›")]
        self.case.assertEqual(len(marked), 1, lines)
        return marked[0]

    def click(self, col, row):
        """The left button down and up at `col`, `row`, as a terminal in mode 1006 reports it."""
        self.send(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode())

    def leave(self):
        self.send(b"q")
        self.case.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])

    def record(self, seat):
        return json.loads((self.home / ".agentkit/state" / f"session-{seat}.json").read_text())


class SessionModels(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": str(self.root), "created": 100})
        config.save_session(self.cfg, "old", "opus", ["opus", "astra"],
                            {"cwd": str(self.root), "created": 100})

    def selected(self, name):
        record = config.load_session(self.cfg, name)
        found = {"orchestrator": record["orchestrator"], "workers": list(record["workers"])}
        if "reviewers" in record:
            found["reviewers"] = list(record["reviewers"])
        return found

    def notes(self):
        return {name: "" for name in config.offered(self.cfg)}

    def test_a_flip_saves_to_the_session_record_at_once(self):
        selected = self.selected("fix-api")
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}), "")
        self.assertEqual(selected["workers"], ["opus", "astra", "fable"])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual(record["workers"], ["opus", "astra", "fable"])
        self.assertEqual(record["reviewers"], ["astra"])
        self.assertEqual(record["orchestrator"], "opus")
        selected = self.selected("fix-api")
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "opus", 2, {}), "")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"],
                         ["astra", "opus"])

    def test_a_legacy_record_shows_workers_in_both_columns_until_the_first_flip(self):
        self.assertNotIn("reviewers", config.load_session(self.cfg, "old"))
        with patch.object(terminal, "layout_width", return_value=100):
            lines, places = menu.session_models_body(self.cfg, self.selected("old"),
                                                     self.notes())
        self.assertEqual(lines[0].split(), ["orch", "exec", "review"])
        rows = {terminal.plain(line): marks(line) for line in lines if marks(line)}
        self.assertEqual(rows[next(line for line in rows if "Opus 5.5" in line)], "●■■")
        self.assertEqual(rows[next(line for line in rows if "Fable 5.1" in line)], "○□□")
        cells = next(cells for name, cells in places.values() if name == "opus")
        self.assertEqual([cell[2] for cell in cells], [0, 1, 2])
        selected = self.selected("old")
        self.assertEqual(menu.session_mark(self.cfg, "old", selected, "opus", 1, {}), "")
        record = config.load_session(self.cfg, "old")
        self.assertEqual(record["workers"], ["astra"])
        self.assertEqual(record["reviewers"], ["opus", "astra"])

    def test_each_group_keeps_one_model_and_no_pair_is_refused_without_a_save(self):
        config.save_session(self.cfg, "solo", "opus", ["opus"], {"reviewers": ["astra"]})
        selected = self.selected("solo")
        self.assertEqual(menu.session_mark(self.cfg, "solo", selected, "opus", 1, {}),
                         "exec needs one model")
        self.assertEqual(menu.session_mark(self.cfg, "solo", selected, "astra", 2, {}),
                         "review needs one model")
        self.assertEqual(config.load_session(self.cfg, "solo")["workers"], ["opus"])
        config.save_session(self.cfg, "tight", "opus", ["opus"],
                            {"reviewers": ["opus", "astra"]})
        selected = self.selected("tight")
        # Opus reviewing itself could start, so removing Astra saves.
        self.assertEqual(menu.session_mark(self.cfg, "tight", selected, "astra", 2, {}),
                         "")
        self.assertEqual(selected["reviewers"], ["opus"])
        self.assertEqual(config.load_session(self.cfg, "tight")["reviewers"], ["opus"])
        # Nothing runnable refuses, without touching the saved groups.
        down = usage.Readings({})
        down.harnesses = {"claude": "claude is not logged in",
                          "codex": "codex is not logged in"}
        with patch.object(config, "update_session") as saved:
            self.assertEqual(menu.session_mark(self.cfg, "tight", selected, "fable", 2,
                                               down),
                             "no allowed executor/reviewer pair")
            saved.assert_not_called()
        self.assertEqual(selected["reviewers"], ["opus"])
        self.assertEqual(config.load_session(self.cfg, "tight")["reviewers"], ["opus"])
        selected = self.selected("fix-api")
        before = dict(selected)
        with patch.object(config, "update_session", side_effect=OSError("read only")):
            self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1,
                                               {}), "session: read only")
        self.assertEqual(selected, before)

    def test_runs_launched_next_read_the_new_groups_and_going_runs_keep_theirs(self):
        selected = self.selected("fix-api")
        menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {})
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}), \
                patch.object(run, "refresh_seat_tally"), \
                patch.object(run, "history_start"), patch.object(run, "claim_slot"):
            directory = config.RUNS / "next-run"
            directory.mkdir()
            run.capture_launch(directory, cfg=self.cfg)
            state = run.read_state(directory)
        self.assertEqual(state["workers"], ["opus", "astra", "fable"])
        self.assertEqual(state["reviewers"], ["astra"])
        going = {"run_id": "going", "launched_session": "fix-api",
                 "workers": ["opus", "astra"], "reviewers": ["astra"]}
        selected = self.selected("fix-api")
        menu.session_mark(self.cfg, "fix-api", selected, "spark", 2, {})
        self.assertEqual(run.run_workers(self.cfg, going), ["opus", "astra"])
        self.assertEqual(run.run_reviewers(self.cfg, going), ["astra"])

    def test_the_body_holds_the_current_groups_and_a_spent_note(self):
        noted = self.notes()
        noted["opus"] = "spent · resets Fri 14:00"
        with patch.object(terminal, "layout_width", return_value=100):
            lines, _ = menu.session_models_body(self.cfg, self.selected("fix-api"), noted,
                                                "opus", 1)
        rows = {terminal.plain(line): marks(line) for line in lines if marks(line)}
        self.assertEqual(len(rows), len(config.offered(self.cfg)))
        self.assertEqual(rows[next(line for line in rows if "Opus 5.5" in line)], "●■□")
        self.assertEqual(rows[next(line for line in rows if "Astra" in line)],
                         "○■■")
        row = next(line for line in lines if "Opus 5.5" in terminal.plain(line))
        self.assertIn("spent · resets Fri 14:00", terminal.plain(row))
        with patch.object(terminal, "layout_width", return_value=40):
            lines, _ = menu.session_models_body(self.cfg, self.selected("fix-api"), noted,
                                                None, 0)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))

    def test_a_dry_run_draws_it_once_and_a_seat_without_a_record_says_so(self):
        with patch.object(menu.usage, "collect", return_value={}), \
                patch.object(terminal, "layout_width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            menu.show_session_models("fix-api", dry_run=True)
        screen = out.getvalue()
        self.assertIn("agentkit · fix-api models", screen)
        self.assertIn("orch", screen)
        self.assertIn("exec", screen)
        self.assertIn("review", screen)
        self.assertIn("esc back", screen)
        with redirect_stdout(io.StringIO()) as out:
            menu.show_session_models("nobody", dry_run=True)
        self.assertIn("models: nobody has no saved models", out.getvalue())

    def test_the_key_line_and_info_list_m_and_the_pipe_line_is_unchanged(self):
        self.assertIn("m models", menu.TERMINAL_KEYS)
        self.assertIn("m       change the session's models", menu.INFO_KEYS)
        self.assertEqual(menu.KEYS, "n new   x stop   c config   i info   q leave")


class SessionModelsScreen(unittest.TestCase):
    def test_m_opens_the_sessions_current_groups_and_esc_goes_back(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertIn("m models", lines[-1])
        self.assertIn("fix-api", screen.highlighted(lines))
        mark = screen.mark()
        screen.send(b"m")
        shown = screen.models("fix-api", after=mark)
        self.assertEqual(shown[2].split(), ["orch", "exec", "review"])
        rows = {line: marks(line) for line in shown if marks(line)}
        self.assertEqual(rows[next(line for line in rows if "Opus 5.5" in line)], "●■□")
        self.assertEqual(rows[next(line for line in rows
                                   if "Astra" in line)], "○■■")
        self.assertIn("⏎ mark", shown[-1])
        self.assertIn("esc back", shown[-1])
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()
        self.assertNotIn("<opened", screen.text())

    def test_a_flip_saves_to_the_record_at_once(self):
        screen = Screen(self)
        screen.frame()
        mark = screen.mark()
        screen.send(b"m")
        screen.models("fix-api", after=mark)
        screen.send(RIGHT + SPACE)        # Fable, first row, executes: into the workers
        screen.models("fix-api", lambda lines: any(
            "Fable 5.1" in line and marks(line) == "○■□" for line in lines), after=mark)
        record = screen.record("fix-api")
        self.assertEqual(record["workers"], ["opus", "astra", "fable"])
        self.assertEqual(record["reviewers"], ["astra"])
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()

    def test_enter_on_the_orchestrator_moves_the_seat(self):
        screen = Screen(self)
        screen.frame()
        mark = screen.mark()
        screen.send(b"m")
        screen.models("fix-api", after=mark)
        screen.send(b"\r")                    # Fable, first row, orchestrator: move the seat
        screen.models("fix-api", lambda lines: any(
            "Fable 5.1" in line and marks(line) == "●□□" for line in lines), after=mark)
        self.assertEqual(screen.record("fix-api")["orchestrator"], "fable")
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()

    def test_a_refusal_is_one_line_and_leaves_the_record_alone(self):
        screen = Screen(self)
        screen.frame()
        mark = screen.mark()
        screen.send(b"m")
        screen.models("fix-api", after=mark)
        # Claude is down in this child, so Astra leaving executes leaves no
        # runnable worker: refused in one line, and the record stays as it was.
        screen.send(DOWN + DOWN + RIGHT + SPACE)
        shown = screen.models("fix-api", lambda lines: any(
            "no allowed executor/reviewer pair" in line for line in lines), after=mark)
        self.assertEqual([line.strip() for line in shown if "no allowed" in line],
                         ["no allowed executor/reviewer pair"])
        record = screen.record("fix-api")
        self.assertEqual(record["workers"], ["opus", "astra"])
        self.assertEqual(record["reviewers"], ["astra"])
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()

    def test_a_click_on_the_key_lines_m_and_on_a_mark_flip(self):
        screen = Screen(self)
        lines = screen.frame()
        column = lines[-1].index("m models") + 1
        mark = screen.mark()
        screen.click(column, len(lines))
        shown = screen.models("fix-api", after=mark)
        row = next(number for number, line in enumerate(shown, 1) if "Spark 1.3" in line)
        column = shown[2].index("exec") + 2       # inside the executes column
        screen.click(column, row)
        screen.models("fix-api", lambda lines: any(
            "Spark 1.3" in line and marks(line) == "○■□" for line in lines), after=mark)
        self.assertEqual(screen.record("fix-api")["workers"], ["opus", "astra", "spark"])
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()

    def test_a_legacy_seat_shows_its_workers_in_both_columns(self):
        screen = Screen(self)
        screen.frame()
        screen.send(b"j")
        screen.frame(lambda lines: "other-seat" in screen.highlighted(lines))
        mark = screen.mark()
        screen.send(b"m")
        shown = screen.models("other-seat", after=mark)
        rows = {line: marks(line) for line in shown if marks(line)}
        self.assertEqual(rows[next(line for line in rows
                                   if "Astra" in line)], "●■■")
        self.assertEqual(rows[next(line for line in rows if "Opus 5.5" in line)], "○□□")
        mark = screen.mark()
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()


if __name__ == "__main__":
    unittest.main(verbosity=2)

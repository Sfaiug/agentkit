"""one way back, everywhere; offline, through the scripted-input seam.

`q`, Esc and an empty Enter go back on every sub-screen; an arrow key or other
escape sequence is neither Esc nor a key. Every sub-screen is drawn in
`terminal.frame`; every choice is asked through `terminal.ask`. All input below
goes through the existing seam -- a patched `menu.read` -- so no terminal, no
tmux and no HOME are touched; only the prompt strings are asserted through the
seam's call records.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, statusbar, terminal, transitions
from agentkit import record
from fixtures.sandbox import Sandbox, menu_input


SEATS = [{"name": "atoll-fix"}, {"name": "parser"}]


class Back(unittest.TestCase):
    def setUp(self):
        for name, value in (("width", 100), ("height", 30)):
            patcher = patch.object(terminal, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        env.start()
        self.addCleanup(env.stop)

    def config_screen(self, *answers):
        # An empty HOME, so the screen reads the shipped default and the ambient
        # ~/.agentkit -- a config this file promised never to touch -- cannot fail it.
        out = io.StringIO()
        with tempfile.TemporaryDirectory(prefix=".v5u-") as home, \
                patch.object(config, "HOME", Path(home)), \
                patch.object(config, "SECRETS", Path(home) / "secrets"), \
                patch.object(menu, "read", side_effect=list(answers)) as read, \
                redirect_stdout(out):
            menu.show_config(False)
        return out.getvalue(), read

    def test_v5u_c_reads_no_line(self):
        # on a terminal `c` is read with the keys (tests/test_config_matrix.py); from a pipe it
        # is drawn, and the menu goes on
        screen, read = self.config_screen()
        self.assertEqual(read.call_count, 0)
        self.assertTrue(screen.startswith("agentkit · config"), screen)
        # no seat is highlighted from a pipe, so the marks are new seats', under the meters
        self.assertIn("For  new seats", screen)
        lines = terminal.ANSI.sub("", screen).splitlines()
        heads = next(line for line in lines if line.split()[-1:] == ["effort"])
        self.assertEqual(heads.split(), ["orch", "builds", "reviews", "effort"])
        self.assertIn("  Claude ", "\n".join(lines[2:lines.index(heads)]))  # whatever it reads

    def test_v5u_menu_arrow_sequence_is_no_key(self):
        out = io.StringIO()
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                menu_input(side_effect=["\x1b[A", ""]) as read, \
                redirect_stdout(out):
            self.assertEqual(menu.loop({}), 0)
        self.assertEqual(read.call_count, 2)
        self.assertNotIn("not a key", out.getvalue())

    def test_v5u_menu_esc_leaves(self):
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                menu_input(side_effect=["\x1b"]) as read, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop({}), 0)
        self.assertEqual(read.call_count, 1)

    def stop(self, *answers, dry_run=False):
        """The `x` screen against two seats, answering `answers`: what it drew and its reads."""
        out = io.StringIO()
        # The seat's runs are listed through a mock too: the real listing reads ~/.agentkit/runs.
        with patch.object(menu, "read", side_effect=list(answers)) as read, \
                patch.object(transitions, "seat_runs", return_value=[]), \
                redirect_stdout(out):
            menu.stop_session([dict(seat) for seat in SEATS], dry_run)
        return out.getvalue(), read

    def test_v5u_x_says_what_stop_means(self):
        screen, _ = self.stop("1", "n")
        self.assertIn(menu.stop_means(None), " ".join(screen.split()))   # wrapped to the width
        self.assertIn("moves to past sessions, p", screen)

    def test_v5u_status_bar_names_the_one_key(self):
        self.assertEqual(statusbar.HINT, "Ctrl-b m  menu")
        top, _, key, _ = statusbar.lines("herdr", "fable", "working", "tasks x 2/5")
        self.assertEqual(key, "Ctrl-b m#[fg=#6c7086]  menu #[default]")
        self.assertNotIn("Ctrl-b d", key)
        self.assertNotIn("back to menu", key)
        self.assertNotIn("menu here", key)
        self.assertNotIn("Ctrl-b d", top)

    def test_v5u_no_enter_to_go_back_in_menu(self):
        self.assertNotIn("Enter to go back", (REPO / "agentkit" / "menu.py").read_text())

    def test_v5u_frame_headers_and_key_lines(self):
        """`x`, `n` and `c`: framed, and the key line `esc back`."""
        screens = {}
        screens["stop"], _ = self.stop("\x1b")
        out = io.StringIO()
        with patch.object(orch, "taken_names", return_value=[]), \
                patch.object(orch, "ask_name", return_value=None), \
                redirect_stdout(out):
            menu.new_session({}, True)
        screens["new"] = out.getvalue()
        screens["config"], _ = self.config_screen("\x1b")
        for name, screen in screens.items():
            lines = screen.splitlines()
            with self.subTest(screen=name):
                self.assertTrue(lines[0].startswith(f"agentkit · {name}"), lines[0])
                self.assertRegex(lines[0], r"\d\d:\d\d$")
                keys = [line for line in lines if line.startswith("  esc back")]
                self.assertTrue(keys, screen)

    def test_v5u_new_screen_is_framed(self):
        """`n` draws the frame; its questions stay v5v's, untouched."""
        out = io.StringIO()
        with patch.object(orch, "taken_names", return_value=[]), \
                patch.object(orch, "ask_name", return_value=None), \
                redirect_stdout(out):
            self.assertIsNone(menu.new_session({}, True))
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("agentkit · new"), lines[0])
        self.assertTrue(any(line.startswith("  esc back") for line in lines))

    def test_v5u_x_asks_through_terminal_ask(self):
        with patch.object(terminal, "ask", return_value="atoll-fix") as ask:
            self.stop(dry_run=True)
        self.assertEqual(ask.call_args[0][:3], ("Stop", "atoll-fix", ["atoll-fix", "parser"]))

    def test_v5u_x_dry_run_reads_no_real_run(self):
        # The dry run lists the seat's runs through the fixture's mock too: the real listing
        # reads ~/.agentkit/runs, a state this file promised never to touch.
        with patch.object(record, "run_dirs", return_value=[Path("fake-active-run")]), \
                patch.object(record, "read_state") as read_state:
            self.test_v5u_x_asks_through_terminal_ask()
        self.assertEqual(read_state.call_count, 0)

    def test_v5u_ask_takes_a_number_or_a_name(self):
        def ask(answer):
            with redirect_stdout(io.StringIO()):
                return terminal.ask("Stop", "atoll-fix", ["atoll-fix", "parser"],
                                    read=lambda prompt: answer)
        self.assertEqual(ask("2"), "parser")
        self.assertEqual(ask("parser"), "parser")
        self.assertEqual(ask("PARSER"), "parser")
        self.assertIsNone(ask("\x1b"))
        self.assertEqual(ask(""), "")

    def test_v5u_no_banned_strings_on_screens(self):
        """No screen prints `Enter to go back`, `Number [` or `1) ` any more."""
        screens = [self.stop("\x1b")[0], self.config_screen("\x1b")[0]]
        out = io.StringIO()
        with patch.object(orch, "taken_names", return_value=[]), \
                patch.object(orch, "ask_name", return_value=None), \
                redirect_stdout(out):
            menu.new_session({}, True)
        screens.append(out.getvalue())
        for screen in screens:
            with self.subTest(screen=screen.splitlines()[0]):
                self.assertNotIn("Enter to go back", screen)
                self.assertNotIn("Number [", screen)
                self.assertNotIn("1) ", screen)


class Piped(Sandbox):
    """`x` from a pipe through the menu: its watcher reads and publishes in the sandbox's HOME."""

    def test_v5u_x_y_stops(self):
        read, stopped = self.x_from_a_pipe(SEATS, "1", "y")
        stopped.assert_called_once_with("atoll-fix", False)
        prompts = [call.args[0] for call in read.call_args_list]
        self.assertIn("stop atoll-fix and everything it is running? [y/N] ", prompts)

    def test_v5u_x_n_goes_back(self):
        _, stopped = self.x_from_a_pipe(SEATS, "1", "n")
        stopped.assert_not_called()

    def test_v5u_x_empty_goes_back(self):
        _, stopped = self.x_from_a_pipe(SEATS, "2", "")
        stopped.assert_not_called()

    def test_v5u_x_esc_goes_back_before_confirm(self):
        read, stopped = self.x_from_a_pipe(SEATS, "\x1b")
        prompts = [call.args[0] for call in read.call_args_list]
        self.assertEqual(prompts, ["> ", "Stop [atoll-fix]: ", "> "])   # never asked to stop
        stopped.assert_not_called()


if __name__ == "__main__":
    unittest.main()

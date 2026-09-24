"""agentkit v5u: one way back, everywhere; offline, through the scripted-input seam.

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
from agentkit import config, menu, orch, terminal


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

    def info_screen(self, *answers):
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=list(answers)) as read, \
                redirect_stdout(out):
            menu.show_info(False)
        return out.getvalue(), read

    def test_v5u_c_reads_no_line(self):
        # on a terminal `c` is read with the keys (tests/test_config_matrix.py); from a pipe it
        # is drawn, and the menu goes on
        screen, read = self.config_screen()
        self.assertEqual(read.call_count, 0)
        self.assertTrue(screen.startswith("agentkit · config"), screen)
        self.assertIn("orchestrator  worker  effort", screen)

    def test_v5u_i_reads_no_line(self):
        # on a terminal `i` is read with the keys (tests/test_close_and_info.py); from a pipe
        # it is drawn, and the menu goes on
        screen, read = self.info_screen()
        self.assertEqual(read.call_count, 0)
        self.assertTrue(screen.startswith("agentkit · info"), screen)
        self.assertIn("agentkit: you talk to one orchestrator", screen)

    def test_v5u_menu_arrow_sequence_is_no_key(self):
        out = io.StringIO()
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                patch.object(menu, "installed", return_value=""), \
                patch.object(menu, "read", side_effect=["\x1b[A", "q"]) as read, \
                redirect_stdout(out):
            self.assertEqual(menu.loop({}), 0)
        self.assertEqual(read.call_count, 2)
        self.assertNotIn("not a key", out.getvalue())

    def test_v5u_menu_esc_leaves(self):
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                patch.object(menu, "installed", return_value=""), \
                patch.object(menu, "read", side_effect=["\x1b"]) as read, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop({}), 0)
        self.assertEqual(read.call_count, 1)

    def stop(self, *answers, dry_run=False):
        """The `x` flow against two seats, answering `answers`."""
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=list(answers)) as read, \
                patch.object(orch, "cmd_stop", return_value=0) as stopped, \
                redirect_stdout(out):
            menu.stop_session([dict(seat) for seat in SEATS], dry_run)
        return out.getvalue(), read, stopped

    def test_v5u_x_y_stops(self):
        screen, read, stopped = self.stop("1", "y")
        self.assertEqual(stopped.call_args[0][0], ["atoll-fix"])
        prompts = [call.args[0] for call in read.call_args_list]
        self.assertIn("stop atoll-fix and everything it is running? [y/N] ", prompts)
        self.assertIn("The conversation is saved and the seat's number "
                      "reopens it later.", screen)

    def test_v5u_x_n_goes_back(self):
        _, _, stopped = self.stop("1", "n")
        self.assertEqual(stopped.call_count, 0)

    def test_v5u_x_empty_goes_back(self):
        _, _, stopped = self.stop("2", "")
        self.assertEqual(stopped.call_count, 0)

    def test_v5u_x_q_goes_back_before_confirm(self):
        screen, read, stopped = self.stop("q")
        self.assertEqual(read.call_count, 1)   # picked nothing: never asked to stop
        self.assertEqual(stopped.call_count, 0)
        self.assertNotIn("stop atoll-fix? [y/N] ", screen)
        self.assertNotIn("stop atoll-fix? [y/N] ",
                         [call.args[0] for call in read.call_args_list])

    def test_v5u_status_bar_names_the_one_key(self):
        self.assertEqual(orch.HINT, "Ctrl-b m  menu")
        left, right, _ = orch.bar("herdr", "fable", "working", "tasks x 2/5")
        self.assertEqual(right, " Ctrl-b m  menu ")
        self.assertNotIn("Ctrl-b d", right)
        self.assertNotIn("back to menu", right)
        self.assertNotIn("menu here", right)
        self.assertNotIn("Ctrl-b d", left)

    def test_v5u_no_enter_to_go_back_in_menu(self):
        self.assertNotIn("Enter to go back", (REPO / "agentkit" / "menu.py").read_text())

    def test_v5u_frame_headers_and_key_lines(self):
        """`x`, `n`, `c` and `i`: framed, key line first key `q back` -- `esc back` on `c` and
        `i`, which read no line."""
        screens = {}
        screens["stop"], _, _ = self.stop("q")
        out = io.StringIO()
        with patch.object(orch, "taken_names", return_value=[]), \
                patch.object(orch, "ask_name", return_value=None), \
                redirect_stdout(out):
            menu.new_session({}, True)
        screens["new"] = out.getvalue()
        screens["config"], _ = self.config_screen("q")
        screens["info"], _ = self.info_screen("q")
        for name, screen in screens.items():
            lines = screen.splitlines()
            with self.subTest(screen=name):
                self.assertTrue(lines[0].startswith(f"agentkit · {name}"), lines[0])
                self.assertRegex(lines[0], r"\d\d:\d\d$")
                back = "  esc back" if name in ("config", "info") else "  q back"
                keys = [line for line in lines if line.startswith(back)]
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
        self.assertTrue(any(line.startswith("  q back") for line in lines))

    def test_v5u_x_asks_through_terminal_ask(self):
        with patch.object(terminal, "ask", return_value="atoll-fix") as ask, \
                redirect_stdout(io.StringIO()):
            menu.stop_session([dict(seat) for seat in SEATS], True)
        self.assertEqual(ask.call_args[0][:3], ("Stop", "atoll-fix", ["atoll-fix", "parser"]))

    def test_v5u_ask_takes_a_number_or_a_name(self):
        def ask(answer):
            with redirect_stdout(io.StringIO()):
                return terminal.ask("Stop", "atoll-fix", ["atoll-fix", "parser"],
                                    read=lambda prompt: answer)
        self.assertEqual(ask("2"), "parser")
        self.assertEqual(ask("parser"), "parser")
        self.assertEqual(ask("PARSER"), "parser")
        self.assertIsNone(ask("q"))
        self.assertEqual(ask(""), "")

    def test_v5u_no_banned_strings_on_screens(self):
        """No screen prints `Enter to go back`, `Number [` or `1) ` any more."""
        screens = [self.stop("q")[0], self.config_screen("q")[0],
                   self.info_screen("q")[0]]
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


if __name__ == "__main__":
    unittest.main()

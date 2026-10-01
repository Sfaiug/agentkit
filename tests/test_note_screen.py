"""A pause on the menu's alternate screen has its own frame and comes back to a whole screen.

The real menu and key reader run on a pty over a temporary HOME and invented seats, using
test_menu_keys' pty helper. Listings, seat states, usage and opening are faked; no real seat,
tmux server, provider or notification is reached.
"""

import os
from pathlib import Path
import re
import sys
import termios
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import terminal
import test_menu_keys

ESC, ENTER, DOWN = b"\x1b", b"\r", b"\x1b[B"
FETCH_ERROR = "models are unavailable; check your configuration before starting a new session"
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MENU_KEYS_REPO"])
from agentkit import config, menu, orch

cfg = config.load()
config.ensure_dirs()
(config.SECRETS / "discord_webhook").mkdir()   # writing the invented secret fails locally
orch.listing = lambda **_kw: [
    {"name": name, "repo": None, "path": "/", "created": 0}
    for name in ("fix-api", "ship-docs")]
orch.job_notices = lambda: []
orch.taken_names = lambda: {"fix-api", "ship-docs"}
menu.seat_row_state = lambda cfg, session, **_kw: {
    "word": "working", "reason": "", "since": None}
menu.usage_lines = lambda cfg, width: []
menu.Live.probe = lambda self, **_kw: False
menu.Live.look = lambda self, found, **_kw: None
menu.update_first = lambda *args, **_kw: None

def collect(*args, **_kw):
    raise config.Error("models are unavailable; check your configuration before starting a new session")

def open_session(cfg, session, dry_run, **_kw):
    menu.pause("resume: the invented conversation is unavailable", "try again later")

menu.usage.collect, menu.open_session = collect, open_session
sys.exit(menu.loop(cfg, dry_run=os.environ["MENU_KEYS_SAVED"] != "1"))
"""


class Screen(test_menu_keys.Menu):
    def __init__(self, case, dry_run=False, cols=100):
        # The helper supplies HOME; inherited worker and seat markers belong to no test.
        env = {name: "" for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG",
                                    "AGENTKIT_SESSION", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE")}
        env.update(AK_RUN_DEPTH="0", AK_MAX_RUNS="0")
        with patch.object(test_menu_keys, "CHILD", CHILD), patch.dict(os.environ, env):
            super().__init__(case, ["fix-api", "ship-docs"], saved=not dry_run, cols=cols)

    def screen(self, name, after=0, where=None):
        """A complete frame, including its header, content, blank line and keys."""
        def ready(text):
            for part in reversed(text[after:].split("\x1b[H")[1:]):
                if "\x1b[J" not in part:
                    continue
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if (lines and re.fullmatch(rf"agentkit · {re.escape(name)} +\d\d:\d\d", lines[0])
                        and (where is None or where(lines))):
                    return lines
            return None
        return self.until(ready, f"the {name} frame")


class NoteScreen(unittest.TestCase):
    def note(self, screen, message, after=0, width=100):
        lines = screen.screen("note", after)
        self.assertEqual(" ".join(line.strip() for line in lines[2:-2]), message)
        self.assertTrue(all(line.startswith("  ") for line in lines[2:-2]), lines)
        self.assertEqual(lines[-2:], ["", "  esc back"])
        self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
        self.assertNotIn("\x1b[?1049l", screen.text()[after:])
        self.assertNotIn("\x1b[?1049h", screen.text()[after:])
        return lines

    def back(self, screen, key, before):
        mark = len(screen.text())
        screen.send(key)
        self.assertEqual(screen.frame(after=mark)[1:], before[1:])

    def test_dry_run_solo_note_and_both_back_keys_restore_the_highlighted_menu(self):
        for width, key in ((100, ESC), (40, ENTER)):
            with self.subTest(width=width, key=key):
                screen = Screen(self, dry_run=True, cols=width)
                screen.frame()
                screen.send(DOWN)
                before = screen.frame(lambda lines: "ship-docs" in screen.highlighted(lines))
                mark = len(screen.text())
                screen.send(b"s")
                self.note(screen, "would toggle solo for ship-docs", mark, width)
                self.back(screen, key, before)
                screen.leave()
                self.assertEqual(termios.tcgetattr(screen.slave), screen.before)

    def test_solo_on_a_missing_record_is_a_note_and_enter_keeps_the_menu_open(self):
        screen = Screen(self)
        before = screen.frame()
        mark = len(screen.text())
        screen.send(b"s")
        self.note(screen, "no orchestrator session 'fix-api'", mark)
        self.back(screen, ENTER, before)
        screen.leave()

    def test_new_session_error_rewraps_on_resize_and_clicking_back_restores_the_menu(self):
        screen = Screen(self, cols=80)
        screen.frame()
        screen.send(b"n")
        screen.screen("new session")
        mark = len(screen.text())
        screen.send(ENTER)
        message = f"new session: {FETCH_ERROR}"
        self.note(screen, message, mark, 80)
        mark = len(screen.text())
        screen.resize(40, 40)
        lines = self.note(screen, message, mark, 40)
        row, keys = next((row, line) for row, line in enumerate(lines, 1) if "esc back" in line)
        mark = len(screen.text())
        screen.click(keys.index("esc back") + 1, row)
        returned = screen.frame(after=mark)
        self.assertIn("fix-api", screen.highlighted(returned))
        self.assertTrue(any("ship-docs" in line for line in returned))
        self.assertFalse(any("new session:" in line for line in returned))
        self.assertTrue(all(terminal.cells(line) <= 40 for line in returned))
        self.assertEqual(list((screen.seats.parent / ".agentkit/state").glob("session-*.json")), [])
        screen.leave()

    def test_a_note_under_config_returns_to_the_whole_config_screen(self):
        screen = Screen(self)
        screen.frame()
        screen.send(b"c")
        screen.screen("config")
        mark = len(screen.text())
        screen.send(DOWN * 30 + b"\x1b[A")   # Discord, above Version
        before = screen.screen("config", after=mark,
                               where=lambda lines: any(line.startswith("›") and "Discord" in line
                                                       for line in lines))
        self.assertIn("Discord", screen.highlighted(before))
        screen.send(ENTER)
        screen.screen("config · discord")
        mark = len(screen.text())
        screen.send(b"https://acme.invalid/hook\rowner\r")
        lines = screen.screen("note", after=mark)
        self.assertTrue(" ".join(line.strip() for line in lines[2:-2]).startswith("discord: "))
        self.assertNotIn("\x1b[?1049l", screen.text()[mark:])
        mark = len(screen.text())
        screen.send(ESC)
        self.assertEqual(screen.screen("config", after=mark)[1:], before[1:])
        mark = len(screen.text())
        screen.send(ESC)
        screen.frame(after=mark)
        screen.leave()

    def test_a_note_after_the_terminal_is_given_back_still_prints_its_lines(self):
        screen = Screen(self)
        before = screen.frame()
        mark = len(screen.text())
        screen.send(b"1")
        screen.saw("resume: the invented conversation is unavailable", "try again later",
                   "esc back ", after=mark)
        said = terminal.ANSI.sub("", screen.text()[mark:])
        self.assertIn("resume: the invented conversation is unavailable\r\ntry again later\r\n", said)
        self.assertNotIn("agentkit · note", said)
        self.assertIn("\x1b[?1049l", screen.text()[mark:])
        self.back(screen, ESC, before)
        screen.leave()


if __name__ == "__main__":
    unittest.main()

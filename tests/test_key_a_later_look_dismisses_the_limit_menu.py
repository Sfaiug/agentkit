"""A look started in the harness's own pane puts Claude's limit menu away, whatever fact stands.

ak put that menu away only at a look while the seat's stored hook fact was a failed turn's
(tests/test_key_a_limit_menu_is_dismissed.py): one drawn later, once another event had replaced
that fact, stood until the tick's pass, three minutes at most, and the seat read `needs you`
meanwhile (22 Nov 2026).  The owner, 19 Nov 2026: "Should always pick stop and wait for limit to
reset"; asked whether ak should check for it on every later event, 20 Nov: "Yes, build it";
asked on 26 Nov 2026 whether to drop sessions naming no launch pane: "Build them".  So a look
started in the pane ak launched the harness in, or in a session naming no launch pane, sends the
menu's key at its own pane, and only there: a look from another pane of a session naming its
launch pane sends none.
Black-box: the seat of tests/test_key_a_limit_menu_is_dismissed.py, whose harness draws its
screen again when its file changes, its hooks fired as Claude fires them, and the look a seat's
wrapper starts with no event (agentkit/looker.py, as tools/codex-seat.py starts it); no tick runs.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.akpane import stamp
from fixtures.hookdrive import ROOT, _env
from test_key_a_limit_menu_is_dismissed import MENU, STOP, LimitSeat

ENDED = {"tool_name": "ExitPlanMode"}    # a PostToolUse that answers nothing


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ALaterLookDismissesTheLimitMenu(LimitSeat, unittest.TestCase):
    def failed_then(self, screen):
        """A failed turn's hook heard at the prompt, then `screen` drawn, then PostToolUse."""
        seat = self.seat("claude-prompt-pane.txt")
        self.fire("StopFailure", {"error": "rate_limit"}, pane=seat)
        seat.show(screen)
        self.fire("PostToolUse", ENDED, pane=seat)
        return seat

    def window(self, seat):
        """A second window in the seat's session, selected, its pane drawing the menu too: that
        pane, as `fire` takes one, and what it was typed so far."""
        screen, typed = (seat.screen_file.with_name(f"other.{end}") for end in ("txt", "typed"))
        screen.write_text(MENU)
        done = self.home.tmux("new-window", "-t", "=acme:", "-P", "-F", "#{pane_id}", shlex.join(
            [sys.executable, str(seat.program), str(screen), str(typed)]))
        self.assertEqual(done.code, 0, done.err)
        pane, deadline = done.out.strip(), time.monotonic() + 30
        while self.home.tmux("display-message", "-p", "-t", pane,
                             "#{pane_title}").out.strip() != stamp(MENU.encode(), 0):
            self.assertLess(time.monotonic(), deadline, "the second window never drew its menu")
            time.sleep(0.05)
        return types.SimpleNamespace(pane=pane), lambda: typed.read_text() if typed.exists() else ""

    def published(self):
        """The word the look left the seat's record with: `word` looks again, and publishes."""
        return json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())["word"]

    def put_away(self, seat):
        """The seat's pane got Esc and nothing else, shows no menu, and the look left the seat
        not the owner's."""
        self.assertEqual(seat.typed(), "\x1b")
        self.assertNotIn(STOP, seat.capture())
        self.assertNotEqual(self.published(), "needs you")

    def test_a_look_at_a_later_event_puts_it_away(self):
        self.put_away(self.failed_then(MENU))

    def test_the_look_a_seats_wrapper_starts_puts_it_away(self):
        seat = self.seat(MENU, heard=False)
        done = self.home.run("python3", str(ROOT / "agentkit" / "looker.py"), "acme",
                             env=_env(self.home, "acme", seat, None))
        self.assertEqual(done.code, 0, done.err)
        self.put_away(seat)

    def test_only_a_look_from_the_harnesss_pane_keys_it_and_only_there(self):
        seat = self.seat(MENU, heard=False)
        other, typed = self.window(seat)
        self.fire("PostToolUse", ENDED, pane=other)
        self.assertEqual((seat.typed(), typed()), ("", ""))
        self.fire("PostToolUse", ENDED, pane=seat)
        self.assertEqual((seat.typed(), typed()), ("\x1b", ""))

    def test_a_session_naming_no_launch_pane_is_keyed_at_the_looks_own_pane(self):
        seat = self.seat(MENU, heard=False)
        done = self.home.tmux("set-option", "-u", "-t", "=acme:", "@ak_harness_pane")
        self.assertEqual(done.code, 0, done.err)
        self.fire("PostToolUse", ENDED, pane=seat)
        self.put_away(seat)

    def test_a_session_naming_no_launch_pane_keys_the_looks_pane_with_another_window_selected(self):
        seat = self.seat(MENU, heard=False)
        done = self.home.tmux("set-option", "-u", "-t", "=acme:", "@ak_harness_pane")
        self.assertEqual(done.code, 0, done.err)
        _, typed = self.window(seat)
        self.fire("PostToolUse", ENDED, pane=seat)
        self.assertEqual((seat.typed(), typed()), ("\x1b", ""))
        self.assertNotIn(STOP, seat.capture())

    def test_a_launch_pane_set_on_the_window_alone_is_none(self):
        seat = self.seat(MENU, heard=False)
        other, typed = self.window(seat)
        # Set on the window alone to another pane, so reading it would withhold Esc from `seat`.
        done = self.home.tmux("set-option", "-u", "-t", "=acme:", "@ak_harness_pane", ";",
                              "set-option", "-w", "-t", "=acme:", "@ak_harness_pane", other.pane)
        self.assertEqual(done.code, 0, done.err)
        self.fire("PostToolUse", ENDED, pane=seat)
        self.assertEqual((seat.typed(), typed()), ("\x1b", ""))
        self.assertNotIn(STOP, seat.capture())

    def test_the_trust_dialog_gets_no_key(self):
        seat = self.failed_then("claude-dialog-pane.txt")
        self.assertEqual(seat.typed(), "")
        self.assertEqual(self.published(), "needs you")


if __name__ == "__main__":
    unittest.main()

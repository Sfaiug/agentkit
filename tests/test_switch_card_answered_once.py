"""A move's line its harness asks about (`[switch] asks`) is answered yes once, however it went in.

Through ak's editor, as a line goes past text the owner left standing, its card is answered as
one typed as keys is, and the text goes back once the move is delivered; and no yes goes while
the seat's terminal holds input unread, as the yes of a pass before, which would outlive the
card into its composer.  Offline: tests/fixtures/editor_seat.py's seat, its harness drawing
Claude Code's card after the line that raises it until `1` comes, then its empty composer."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.editor_seat import EditorSeat
from fixtures.seats import PANE, SEAT
from agentkit import config, watch

MODEL, EFFORT = "/model claude-fable-5-1", "/effort xhigh"
CARD = """   Switch model?
   Your next response will be slower and use more tokens

   This conversation is cached for the current model. Switching to Sonnet 5.5 means
   the full history gets re-read.

   ❯ 1. Yes, switch to Sonnet 5.5
     2. No, go back
"""


class SwitchCardAnsweredOnce(EditorSeat):
    def setUp(self):
        super().setUp()
        self.asks, self.card = {}, False
        config.update_session(SEAT, orchestrator="fable")

    def press(self, key, pane=PANE):
        if self.card:       # every key goes to the card, and `1` takes it
            self.keys.append(key)
            if key == "1":
                self.card = False
                self.show("")
            return
        raised = self.asks.get(self.composer) if key == "Enter" else None
        super().press(key, pane)
        if raised:
            self.card, self.pane, self.late = True, raised, 0

    def tell(self, times, *lines):
        watch.owe_line(SEAT, None, *({"line": line, "switch": True, "pane": PANE}
                                     for line in lines))
        for _ in range(times):
            watch.tell_owed(SEAT, lambda _: None, self.cfg)

    def test_a_line_in_through_ak_s_editor_is_answered_and_its_text_goes_back(self):
        for line, title in ((MODEL, "Switch model?"), (EFFORT, "Change effort level?")):
            with self.subTest(title=title):
                self.asks, self.sent = {line: CARD.replace("Switch model?", title)}, []
                self.show("Please keep my draft")
                self.untouched(watch.DRAFT_STILL + 1)
                self.tell(3, line)
                self.assertFalse(self.card)
                self.assertEqual(self.sent, [line])
                self.assertEqual(self.composer, "Please keep my draft")
                self.assertEqual(watch.seat_read(SEAT).get("owed_lines"), None)

    def test_no_yes_goes_while_the_terminal_holds_input_unread(self):
        self.asks = {MODEL: CARD}
        self.tell(1, MODEL, EFFORT)
        self.assertTrue(self.card)
        self.unread = True
        watch.tell_owed(SEAT, lambda _: None, self.cfg)
        self.assertNotIn("1", self.keys)
        self.unread = False
        watch.tell_owed(SEAT, lambda _: None, self.cfg)
        watch.tell_owed(SEAT, lambda _: None, self.cfg)
        self.assertEqual((self.keys.count("1"), self.sent), (1, [MODEL, EFFORT]))


if __name__ == "__main__":
    unittest.main()

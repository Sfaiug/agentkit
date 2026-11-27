"""A parked seat publishes why it needs the owner on the tick that reads a refill."""

import json
import time
import unittest

from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from test_key_usage_return_resumes_every_harness import (
    ACCOUNT_LINE, MODELS, parked, reading, refill, resume_pane, usage_wait,
)

HIDDEN = "Session settings\n"


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a boxed watch tick")
class DeferredUsageReturn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.now = time.time()

    def adapters(self, harnesses):
        akconfig.write(self.home, [MODELS[harness] for harness in harnesses])
        return fakeadapter.install(self.home, **dict.fromkeys(harnesses, "pass"))

    def tick_ok(self, result):
        self.assertEqual(result.code, 0, result.out + result.err)

    def published(self, seat, word):
        path = self.home.path / f".agentkit/state/seat-{seat.name}.json"
        state = json.loads(path.read_text())
        self.assertEqual(state["word"], word, state)
        bar = self.home.tmux("show-options", "-qv", "-t", f"={seat.name}:", "@ak_top")
        self.assertIn(word, bar.out)
        return state["usage_wait"]

    def deferred(self, seat, adapter, before, action, continuing=True):
        wait = self.published(seat, "needs you")
        self.assertNotIn("until", wait)
        self.assertIn("usage is back", wait["reason"])
        self.assertIn(action, wait["reason"])
        self.assertIs(wait["continue"], continuing)
        self.assertEqual(wait["since"], self.now - 600)
        self.assertTrue(wait["field_deferred"])
        self.assertEqual(adapter.calls("interactive"), [])
        self.assertEqual(seat.capture(), before)
        self.assertEqual(seat.typed(), "")

    def owned(self, screens, action, continuing=True):
        fakes = self.adapters(screens)
        seats = {}
        for harness, screen in screens.items():
            seat = parked(self.home, harness, self.now, continuing)
            resume_pane(self.home, seat, harness, fakes[harness])
            prompt = seat.screen
            seat.show(screen)
            seats[harness] = seat, prompt, seat.capture()

        self.tick_ok(refill(self.home, fakes, self.now))
        for harness, (seat, prompt, before) in seats.items():
            with self.subTest(harness=harness):
                self.deferred(seat, fakes[harness], before, action, continuing)

        menu = self.home.ak("--dry-run")
        self.assertEqual(menu.code, 0, menu.err)
        for seat, prompt, _ in seats.values():
            self.assertRegex(menu.out, rf"{seat.name}[^\n]*needs you")
            seat.show(prompt)

        self.tick_ok(self.home.tick())
        for harness, (seat, _, _) in seats.items():
            with self.subTest(harness=harness):
                self.assertIsNone(self.published(seat, "working" if continuing else "idle"))
                launch, = fakes[harness].calls("interactive")
                self.assertIn(seat.record["conversation"], launch["argv"])
                if not continuing:
                    self.assertFalse(launch["env"].get("AGENTKIT_FIRST_PROMPT"))
                    self.assertEqual(seat.typed(), "")
                elif harness == "muse":
                    self.assertEqual(seat.lines(), [ACCOUNT_LINE])
                else:
                    self.assertEqual(launch["env"]["AGENTKIT_FIRST_PROMPT"], ACCOUNT_LINE)

    def test_a_hidden_composer_on_every_harness(self):
        self.owned(dict.fromkeys(MODELS, HIDDEN), "screen")

    def test_an_owner_draft(self):
        self.owned({"claude": "claude-draft-pane.txt"}, "empty the input field")

    def test_a_scrolled_draft(self):
        self.owned({"claude": "claude-ten-row-draft-pane.txt"}, "empty the input field")

    def test_an_idle_seat_waits_then_reopens_without_starting_a_turn(self):
        self.owned({"muse": HIDDEN}, "screen", continuing=False)

    def test_the_owner_can_start_the_turn_while_deferred(self):
        fakes = self.adapters(["claude"])
        seat = parked(self.home, "claude", self.now)
        seat.show("claude-draft-pane.txt")
        before = seat.capture()
        self.tick_ok(refill(self.home, fakes, self.now))
        self.deferred(seat, fakes["claude"], before, "empty the input field")
        seat.show("claude-working-pane.txt")
        self.home.write(f".agentkit/state/hook-{seat.name}.json", {
            "session": seat.name, "event": "UserPromptSubmit", "at": time.time()})
        self.tick_ok(self.home.tick())
        self.assertIsNone(self.published(seat, "working"))
        self.assertEqual(fakes["claude"].calls("interactive"), [])
        self.assertEqual(seat.typed(), "")

    def test_an_unowned_seat_can_run_out_again_then_continue_in_place(self):
        fakes = self.adapters(["muse"])
        seat = Seat(self.home, "fix-api", model="spark", screen=HIDDEN,
                    record={"conversation": None}, asks={"continue": "muse-working-pane.txt"})
        usage_wait(self.home, seat, "muse", self.now, continuing=True)
        before = seat.capture()
        self.tick_ok(refill(self.home, fakes, self.now))
        self.deferred(seat, fakes["muse"], before, "screen")

        spent = reading(self.now + 600, 100)
        self.home.write(".agentkit/state/usage.json", {"providers": {
            "meta": {**spent, "provider": "meta", "resets": 0}}, "fetched_at": self.now,
            "reset_checked_at": self.now})
        fakes["muse"].answer("usage", json.dumps(spent))
        self.tick_ok(self.home.tick())
        wait = self.published(seat, "out of usage")
        self.assertEqual(wait["until"], spent["meters"][0]["resets_at"])
        self.assertFalse(wait.get("field_deferred"))
        self.assertEqual(seat.capture(), before)
        self.assertEqual(seat.typed(), "")

        self.tick_ok(refill(self.home, fakes, self.now))
        self.deferred(seat, fakes["muse"], before, "screen")
        seat.show("muse-prompt-pane.txt")
        self.tick_ok(self.home.tick())
        self.assertIsNone(self.published(seat, "working"))
        self.assertEqual(seat.lines(), ["continue"])
        self.assertEqual(fakes["muse"].calls("interactive"), [])


if __name__ == "__main__":
    unittest.main()

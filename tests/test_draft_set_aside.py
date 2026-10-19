"""Text the owner left standing in a seat's composer never keeps ak's line out of it.

A seat ended its turn on `ak wait`; the run merged, and its end could not be typed in while the
owner's unsent text held the composer, so the seat sat and the owner was paged (19 Oct 2026).
Once that text has stood unchanged a while, ak sets it aside with the harness's own keys, types
its line, and brings the text back.  Offline: fixtures.seats' throwaway seats, its tmux faked
as a composer with Claude Code's prompt history.
"""

from contextlib import contextmanager
import re
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, REPO, SEAT, Seats
from agentkit import orch, watch

DRAFT = "and add these posts"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.composer, self.history, self.up, self.keys = DRAFT, [], 0, []
        self.show()

    def show(self):
        self.pane = (self.base.replace(self.empty, f"❯ {self.composer}\n") if self.composer
                     else self.base)
        self.free = not self.composer

    def tmux(self, *args, **kwargs):
        if args[0] != "send-keys":
            return super().tmux(*args, **kwargs)
        key = args[-1]
        self.keys.append("text" if "-l" in args else key)
        if "-l" in args:
            self.typed.append(key)
            self.composer += key
        elif key in ("Enter", "C-c"):
            # what Ctrl-C empties is filed in the history beside what Enter sends
            self.history.append(self.composer)
            self.composer, self.up = "", 0
        elif key == "Up":
            self.up += 1
            self.composer = self.history[-self.up]
        self.show()
        return 0, ""

    def later(self, seconds):
        watch.time.time = lambda: NOW + seconds

    def test_a_draft_that_stood_still_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.tick()
        self.assertEqual(self.keys, [])
        self.later(watch.DRAFT_STILL)
        self.tick()
        self.assertEqual(self.keys, ["C-c", "text", "Enter", "Up", "Up"])
        self.assertEqual(self.typed, [LINE])
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_a_draft_still_changing_is_left_alone(self):
        self.wait_line()
        for step in range(3):
            self.composer += " more"
            self.show()
            self.later(step * watch.DRAFT_STILL)
            self.tick()
        self.assertEqual(self.keys, [])
        self.assertFalse(self.told())

    def test_a_line_that_could_not_go_in_puts_the_draft_back_untouched(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        # the owner's next key arrives right after the draft is set aside
        unread = iter([False, False, True])
        with patch.object(watch, "pane_unread", side_effect=lambda _seat: next(unread, False)):
            self.tick()
        self.assertEqual(self.keys, ["C-c", "Up"])
        self.assertEqual(self.typed, [])
        self.assertEqual(self.composer, DRAFT)
        self.assertFalse(self.told())

    def test_a_draft_edited_or_emptied_starts_its_two_minutes_again(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL - 1)
        self.composer = ""
        self.show()
        with patch.object(watch, "pane_unread", return_value=True):
            self.tick()
        for step, edit in enumerate((DRAFT, DRAFT + " "), 1):
            self.composer = edit
            self.show()
            self.later(step * watch.DRAFT_STILL)
            self.tick()
        self.assertEqual(self.keys, [])

    def test_a_turn_started_before_the_lock_gets_no_key(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        held = watch.seat_held
        working = (REPO / "tests/fixtures/claude-draft-while-working-pane.txt").read_text(
            encoding="utf-8").replace("draft typed while working", DRAFT)

        @contextmanager
        def started(name):
            with held(name) as seat:
                self.pane, self.free = working, False
                yield seat
        with patch.object(watch, "seat_held", side_effect=started):
            self.tick()
        self.assertEqual(self.keys, [])

    def test_a_pass_stopped_before_its_line_puts_the_draft_back_next(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        with patch.object(watch, "_send_line", side_effect=InterruptedError):
            self.assertRaises(InterruptedError, self.tick)
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_a_key_that_could_not_bring_the_draft_back_is_pressed_next_pass(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        tmux = orch.tmux_out
        with patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: (
                (1, "no server") if args[0] == "send-keys" and args[-1] == "Up"
                else tmux(*args, **kw))):
            self.tick()
        self.assertFalse(self.told())
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_a_delivery_the_caller_missed_is_still_delivered_next_pass(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        mark = watch.wait_mark
        with patch.object(watch, "wait_mark", side_effect=lambda name, wait, **marks: (
                mark(name, wait, **marks) if "told" not in marks else False)):
            self.tick()
        self.tick()
        self.assertEqual(self.keys, ["C-c", "text", "Enter", "Up", "Up"])
        self.assertTrue(self.told())

    def test_the_draft_back_before_any_enter_delivers_nothing(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        tmux = orch.tmux_out

        def owner_takes_it_back(*args, **kw):
            done = tmux(*args, **kw)
            if args[0] == "send-keys" and "-l" in args:
                for key in ("C-c", "Up", "Up"):     # ak's unsent line out, their draft back
                    self.tmux("send-keys", "-t", f"={SEAT}:", key)
            return done
        with patch.object(orch, "tmux_out", side_effect=owner_takes_it_back):
            self.tick()
        self.assertNotIn("Enter", self.keys)
        self.assertFalse(self.told())

    def keyed(self, key, done):
        """tmux with `key` answered by `done(args)`, None passing it on to the composer."""
        tmux = orch.tmux_out
        return patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: (
            done(args) if args[0] == "send-keys" and args[-1] == key else None)
            or tmux(*args, **kw))

    def test_a_draft_half_brought_back_is_finished_from_where_it_stands(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        ups = []
        with self.keyed("Up", lambda _: ups.append(1) or (1, "no server") if ups else
                        ups.append(1)):
            self.tick()
        self.assertEqual(self.composer, LINE)
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertEqual(self.keys.count("Enter"), 1)
        self.assertTrue(self.told())

    def test_a_key_the_composer_did_not_take_is_pressed_again_before_the_line_is_told(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        with self.keyed("Up", lambda _: (0, "")):
            self.tick()
        self.assertFalse(self.told())
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_another_line_waits_for_the_draft_to_come_back(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        with self.keyed("Up", lambda _: (1, "no server")):
            self.tick()
        watch.type_at_prompt(self.seat, "The acme docs build ended.", lambda _: None,
                             cfg=self.cfg)
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_an_enter_that_failed_delivers_nothing_when_the_owner_takes_the_line_back(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        with self.keyed("Enter", lambda _: (1, "no server")):
            self.tick()
        for key in ("C-c", "Up", "Up"):
            self.tmux("send-keys", "-t", f"={SEAT}:", key)
        self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertFalse(self.told())

    def test_the_line_the_owner_sent_brings_the_draft_back(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        tmux = orch.tmux_out

        def owner_sends_it(*args, **kw):
            done = tmux(*args, **kw)
            if args[0] == "send-keys" and "-l" in args:
                self.tmux("send-keys", "-t", f"={SEAT}:", "Enter")
            return done
        with patch.object(orch, "tmux_out", side_effect=owner_sends_it):
            self.tick()
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())

    def test_a_row_or_space_added_to_the_draft_starts_its_two_minutes_again(self):
        for edit in ("\n", "\n  ? for shortcuts"):
            with self.subTest(edit=edit):
                self.composer, self.keys = DRAFT, []
                self.show()
                self.later(0)
                self.wait_line()
                self.tick()
                self.later(watch.DRAFT_STILL)
                self.composer += edit
                self.show()
                self.tick()
                self.assertEqual(self.keys, [])
        held = watch.seat_held

        @contextmanager
        def edited(name):
            with held(name) as seat:
                self.composer += " "
                self.show()
                yield seat
        self.later(3 * watch.DRAFT_STILL)
        with patch.object(watch, "seat_held", side_effect=edited):
            self.tick()
        self.assertEqual(self.keys, [])

    def test_the_trays_clock_does_not_hold_the_draft(self):
        self.base = (REPO / "tests/fixtures/claude-tray-idle-pane.txt").read_text(
            encoding="utf-8")
        self.empty = re.search(r"(?m)^.*❯\xa0.*\n", self.base).group()
        self.show()
        self.wait_line()
        self.tick()
        for seconds in (watch.DRAFT_STILL, 2 * watch.DRAFT_STILL):
            self.later(seconds)
            self.base = re.sub(r"\d+s · ↓", f"{seconds}s · ↓", self.base)
            self.show()
            self.tick()
        self.assertTrue(self.told())


if __name__ == "__main__":
    unittest.main()

"""Text ak's editor keeps of a seat's composer, set aside for a line or given back, keeps every
line of ak's from going in as keys: the composer can draw that text late, reading empty while it
holds it, and keys typed there would join it.  So does a seat tmux cannot say is one launched
with that editor, or what that editor keeps.  Every key goes to the pane checked, whichever the
owner selects meanwhile.  Offline: fixtures.editor_seat.
"""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE
from agentkit import aside_editor, orch, watch


class KeysWaitOnKeptText(EditorSeat):
    def typed_line(self):
        return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)

    def test_text_the_editor_keeps_holds_back_a_line_its_empty_screen_would_take(self):
        for state in (aside_editor.ASIDE, aside_editor.GIVEN):
            with self.subTest(state=state):
                self.buffers = {aside_editor.kept(PANE): aside_editor.pack(
                    state, b"an earlier line", b"and add these posts")}
                self.assertFalse(self.typed_line())
        self.buffers.clear()
        tmux = orch.tmux_out
        for ask in ("#{pane_id}", "#{buffer_name}"):         # the seat's pane, or what is kept
            with self.subTest(ask=ask), patch.object(
                    orch, "tmux_out", side_effect=lambda *args, **kw: (1, "no server") if (
                        args[-1].startswith(ask)) else tmux(*args, **kw)):
                self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.keys, self.typed, self.sent), (["Enter"], [LINE], [LINE]))

    def test_every_key_goes_to_the_pane_checked_whichever_the_owner_selects(self):
        other, tmux, lock = "%8", orch.tmux_out, watch.seat_held
        self.buffers = {aside_editor.kept(other): aside_editor.pack(
            aside_editor.GIVEN, b"an earlier line", b"and add these posts")}
        for moment in ("lock", "list-buffers"):     # while the line waits for its lock, or is checked
            with self.subTest(moment=moment):
                active, strayed, self.sent = [PANE], [], []

                def out(*args, **kw):
                    active[0] = other if args[0] == moment else active[0]
                    target = args[args.index("-t") + 1] if "-t" in args else None
                    if args[0] == "display-message" and args[-1].startswith("#{pane_id}"):
                        return 0, f"{active[0]}\t4242\t{self.tty}"
                    if args[0] == "send-keys" and (
                            active[0] if target == f"={self.seat['name']}:" else target) != PANE:
                        strayed.append(args)
                        return 0, ""
                    return tmux(*args, **kw)

                @contextmanager
                def held(name):
                    active[0] = other if moment == "lock" else active[0]
                    with lock(name) as got:
                        yield got

                with patch.object(orch, "tmux_out", side_effect=out), \
                        patch.object(watch, "seat_held", held):
                    delivered = self.typed_line()
                self.assertEqual((delivered, strayed, self.sent), (True, [], [LINE]))


if __name__ == "__main__":
    unittest.main()

"""The owner's unsent text a switch lifts is back in the new harness's composer as soon as that
harness shows one empty, and the line it opened on is taken, with no tick: whoever lifts it
(`watch.carry_draft`) gives it back by the tick's own rules (`watch.drafts_back`), in a process of
its own (`watch.start_carried_back`), so the switch returns as soon as it did, however long that
holds the seat's lock.  Offline: fixtures.editor_seat's seat, switched as
tests/test_switch_carries_draft.py switches it -- the text lifted and the harness respawned in one
hold of the seat's lock -- that process a thread of the test's; and `orch.switch_orchestrator`.
"""

import json
import threading
import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import NOW
from agentkit import aside_editor, config, notify, orch, watch

DRAFT = "and add these posts\nto the list  \n\n"     # given back byte for byte


class SwitchGivesTheTextBackAtOnce(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(0)                       # the owner was typing into it a moment ago
        self.show(DRAFT)

    def switched(self, owed=None):
        with notify.session_lock(self.seat["name"]):
            self.assertTrue(watch.carry_draft(self.seat, "claude", self.pane, "claude", self.cfg))
            self.show("")
            self.pane = ""                      # the respawned harness, drawing nothing yet
            watch.time.sleep = lambda _seconds: self.show("")     # ... then its empty composer
            if owed:                            # the line it opens on, its first prompt
                watch.relaunched(self.seat["name"], "claude", owed, NOW)
        self.settle()

    def test_the_draft_is_back_once_the_new_harness_shows_its_composer_with_no_tick(self):
        self.switched()
        self.assertEqual((self.composer, self.sent, self.typed), (DRAFT, [], []))
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): aside_editor.pack(
            aside_editor.GIVEN, b"", DRAFT.encode())})
        self.assertEqual(self.keys, ["C-g", "C-g"])     # once to lift, once to hand back

    def test_and_once_the_line_it_opened_on_is_taken(self):
        config.stop_path(self.seat["name"]).write_text(json.dumps({"turn": NOW + 1}))
        self.switched(watch.MIDTURN_LINE)
        self.assertEqual(self.composer, DRAFT)

    def test_the_switch_returns_while_the_hand_back_holds_the_seat_s_lock(self):
        self.cfg["models"]["astra"]["harness"] = "claude"
        config.save(self.cfg)
        holding, returned, waited, forget = (threading.Event(), threading.Event(), [],
                                             watch.forget)

        def hold(name):         # the hand-back, its editor slow to answer
            with notify.session_lock(name):
                holding.set()
                waited.append(returned.wait(5))

        def hand_back(name):
            self.behind.append(threading.Thread(target=hold, args=(name,)))
            self.behind[-1].start()

        def forgotten(*args, **kwargs):     # the switch's cleanup, once the hand-back holds it
            holding.wait(5)
            return forget(*args, **kwargs)
        with patch.multiple(orch, _switch_plan=lambda *_a, **_kw: ("", None),
                            switch_in_place=lambda *_a, **_kw: None, launch=lambda *_a, **_kw: None,
                            seat_conversation=lambda *_a: None, handover=lambda *_a: None,
                            fresh_command=lambda *_a, **_kw: (["acme-harness"], "new")), \
                patch.multiple(watch, start_carried_back=hand_back, forget=forgotten):
            self.assertEqual(orch.switch_orchestrator(
                self.cfg, self.seat["name"], "astra", providers={}), "")
        returned.set()
        self.settle()
        self.assertEqual(waited, [True])


if __name__ == "__main__":
    unittest.main(verbosity=2)

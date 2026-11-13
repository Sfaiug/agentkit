"""A switch that restarts a seat's harness reads, keeps and respawns one pane: the one its launch
recorded (`orch.harness_pane`), whichever window the owner has selected; with none recorded, the
one selected as it reads, whichever the owner selects after.  A capture of it that failed is no
field read empty.

The switch read the selected window's pane, empty, as the seat's field, and respawned the
recorded pane, losing the text the owner had left there unsent; a capture that failed, read as
an empty pane, it took for no field at all.  Offline: a temporary HOME, the seat's tmux faked
with its recorded pane and another window's selected, the respawn's setup faked.
"""

import unittest
from unittest.mock import patch

from fixtures.seats import PROMPT, REPO, SEAT, Seats
from agentkit import orch, statusbar, watch

HARNESS, SELECTED = "%7", "%8"      # the pane the seat's launch recorded, and the one selected
TYPED = (REPO / "tests/fixtures/claude-draft-pane.txt").read_text(encoding="utf-8")
STAYS = f"{SEAT} stays on opus: the text in its input field could not be kept"
CAPTURE = watch.pane_text           # the real capture, of the pane it is asked for


class Preservation(Seats):
    def setUp(self):
        super().setUp()
        self.screens, self.respawned, self.captures = {HARNESS: PROMPT, SELECTED: PROMPT}, [], True
        self.recorded, self.selected = HARNESS, SELECTED
        for target, name, fake in (
                (watch, "pane_text", CAPTURE), (orch, "_switch_plan", lambda *_a, **_kw: ("", None)),
                (orch, "command", lambda _cfg, model, *_a, **_kw: ["acme-tui", model]),
                (orch, "seat_command", lambda *_a: ("acme-tui", self.root / "launch")),
                (orch, "seat_environment", lambda *_a, **_kw: None),
                (orch, "launch", lambda name, model, cwd, cmd, _conversation, session, **_kw:
                 orch._start_harness(name, model, cwd, cmd, session)),
                (statusbar, "dress", lambda *_a: None)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tmux(self, *args, **_kw):
        """The seat's server: `=acme-docs:` is its selected pane, a respawn's harness opens empty."""
        target = args[args.index("-t") + 1] if "-t" in args else ""
        pane = target if target.startswith("%") else self.selected
        if args[0] == "show-options" and args[-1] == orch.PANE_OPTION:
            return 0, self.recorded
        if args[0] == "display-message" and args[-1] == "#{session_name}":
            return 0, SEAT
        if args[0] == "display-message" and args[-1] == "#{pane_id}":
            return 0, pane
        if args[0] == "capture-pane":
            return (0, self.screens[pane]) if self.captures else (1, "can't capture")
        if args[0] == "respawn-pane":
            self.respawned.append(pane)
            self.screens[pane] = PROMPT
            return 0, ""
        return 1, "not in this fixture"

    def switch(self):
        return orch.switch_orchestrator(self.cfg, SEAT, "fable", providers={})

    def test_empty_selected_window_does_not_discard_the_harness_panes_draft(self):
        self.screens[HARNESS] = TYPED
        self.assertEqual(self.switch(), STAYS)
        self.assertEqual((self.respawned, self.screens[HARNESS]), ([], TYPED))

    def test_text_in_the_selected_window_leaves_the_harness_pane_to_move(self):
        self.screens[SELECTED] = TYPED
        self.assertEqual(self.switch(), "")
        self.assertEqual((self.respawned, self.screens[SELECTED]), ([HARNESS], TYPED))

    def test_failed_capture_keeps_the_old_harness_and_text(self):
        self.screens[HARNESS], self.captures = TYPED, False
        self.assertEqual(self.switch(), STAYS)
        self.assertEqual((self.respawned, self.screens[HARNESS]), ([], TYPED))

    def test_with_no_pane_recorded_another_window_selected_meanwhile_keeps_its_draft(self):
        self.recorded, self.selected, self.screens[SELECTED] = "", HARNESS, TYPED

        def command(*_args):
            self.selected = SELECTED    # the owner selects the other window as it is prepared
            return "acme-tui", self.root / "launch"
        orch.seat_command.side_effect = command
        self.assertEqual(self.switch(), "")
        self.assertEqual((self.respawned, self.screens[SELECTED]), ([HARNESS], TYPED))


if __name__ == "__main__":
    unittest.main(verbosity=2)

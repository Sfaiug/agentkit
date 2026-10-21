"""A seat runs at an effort of its own: stepped on `c` under For ‹seat›, or typed inside it.

The owner (20 Oct 2026): "when the user updates the effort or the model in an active session,
the session should update with that from now on, but it should also work the other way
around".  The seat's record holds its own effort, which its launches take over its entry's;
every other seat, and the next one `n` opens, keep the entry's.  Offline: a temporary HOME,
the move a seat makes faked where the screen asks for it, no tmux.
"""

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, harness, menu, orch, terminal, watch
from agentkit.harness import claude

SEAT, THREAD = "acme-api", "6b1d0c4e-0000-4000-8000-00000000000b"


class SeatEffort(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": THREAD, "id_source": harness.LAUNCHER})
        self.moved = []

        def move(cfg, name, model, providers=None, effort=None):
            self.moved.append((name, model, effort))
            config.update_session(name, orchestrator=model, effort=effort)
            return ""
        self.stack.enter_context(patch.object(orch, "switch_orchestrator", side_effect=move))
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=100))
        self.levels = menu.effort_levels(self.cfg["models"]["opus"])
        self.entry = self.cfg["models"]["opus"]["effort"]

    def record(self):
        return config.session_records()[SEAT]

    def row(self, name, scope):
        """`name`'s row on `c` for the For row's `scope`, its words."""
        lines, places = menu.config_body(self.cfg, selected=self.record(), scope=scope)
        line = next(lines[at] for at, (row, _) in places.items() if row == ("model", name))
        return terminal.plain(line).split()

    def test_c_shows_a_seat_its_own_effort_on_its_orchestrator_alone(self):
        own = next(level for level in self.levels if level != self.entry)
        config.update_session(SEAT, effort=own)
        self.assertEqual(self.row("opus", SEAT)[-1], own)
        self.assertEqual(self.row("opus", menu.FOR_SCOPES[0])[-1], self.entry)
        self.assertEqual(self.row("fable", SEAT)[-1], self.cfg["models"]["fable"]["effort"])

    def test_a_step_on_its_orchestrator_moves_that_seat_alone(self):
        before = json.dumps(self.cfg["models"], sort_keys=True)
        nxt = self.levels[(self.levels.index(self.entry) + 1) % len(self.levels)]
        self.assertEqual(menu.seat_effort(self.cfg, SEAT, self.record(), "opus", 1, {}), "")
        self.assertEqual(self.moved, [(SEAT, "opus", nxt)])
        self.assertEqual(menu.seat_effort(self.cfg, SEAT, self.record(), "opus", 0, {}, to=0),
                         "")
        self.assertEqual(self.moved[-1], (SEAT, "opus", self.levels[0]))
        self.assertEqual(json.dumps(self.cfg["models"], sort_keys=True), before)

    def test_an_effort_typed_inside_the_seat_becomes_its_own(self):
        own = next(level for level in self.levels if level != self.entry)
        path = claude.transcript_path(self.record(), THREAD)
        path.parent.mkdir(parents=True)
        for effort in (own, self.entry):
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "assistant", "effort": effort,
                                     "timestamp": datetime.now(timezone.utc).isoformat(),
                                     "message": {"model": self.cfg["models"]["opus"]["model"]}})
                         + "\n")
            watch.follow_model(self.cfg, SEAT)
            self.assertEqual((self.record()["orchestrator"], orch.seat_effort(self.record(), "opus")),
                             ("opus", None if effort == self.entry else own))

    def test_a_launch_takes_the_seats_own_effort_on_its_orchestrator_alone(self):
        config.update_session(SEAT, effort="high")
        self.assertEqual(orch.seat_effort(self.record(), "opus"), "high")
        self.assertIsNone(orch.seat_effort(self.record(), "fable"))
        self.assertIsNone(orch.seat_effort(None, "opus"))


if __name__ == "__main__":
    unittest.main()

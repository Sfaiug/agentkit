"""A switch that restarts a seat's harness happens only over a field ak read empty or text it
lifted: a seat whose model left the config is read through the harness its pane runs, and
stays as it is where its text cannot be lifted or nothing names that harness.

`watch.carry_draft` answered the text kept for such a seat without reading its field, and the
respawn took the text with the old harness.  Offline: fixtures.editor_seat's seat, its record on
a model the config no longer has, the process table and the launch faked.
"""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import EditorSeat
from agentkit import config, orch

DRAFT = "and add these posts\nto the list"
GONE = "retired"            # the model the seat runs, gone from the config
STAYS = "stays on retired: the text in its input field could not be kept"


class SwitchLeavesTextItCannotLift(EditorSeat):
    def setUp(self):
        super().setUp()
        config.update_session(self.seat["name"], orchestrator=GONE)
        self.table, self.relaunched = {4207: (1, ["claude", "--resume", "thread"])}, []

        def launch(_name, model, *_a, **_kw):
            self.relaunched.append(model)
            self.show("")           # the new harness, its composer empty

        for name, fake in (("_switch_plan", lambda *_a, **_kw: ("", None)),
                           ("processes", lambda: self.table),
                           ("command", lambda _cfg, model, *_a, **_kw: ["acme-tui", model]),
                           ("launch", launch)):
            patcher = patch.object(orch, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def switch(self):
        return orch.switch_orchestrator(self.cfg, self.seat["name"], "fable", providers={})

    def record(self):
        return config.session_records()[self.seat["name"]]["orchestrator"]

    def test_a_draft_its_editor_cannot_lift_stays_with_the_harness_it_runs(self):
        self.show(DRAFT)
        self.assertEqual(self.switch(), f"{self.seat['name']} {STAYS}")
        self.assertEqual((self.relaunched, self.record()), ([], GONE))
        self.assertEqual((self.composer, self.sent, self.keys), (DRAFT, [], []))

    def test_a_field_read_empty_through_the_harness_its_pane_runs_switches(self):
        self.assertEqual(self.switch(), "")
        self.assertEqual((self.relaunched, self.record()), (["fable"], "fable"))

    def test_a_pane_running_no_harness_ak_knows_stays_as_it_is(self):
        self.table = {4207: (1, ["bash"])}      # nothing names what draws its field
        self.assertEqual(self.switch(), f"{self.seat['name']} {STAYS}")
        self.assertEqual((self.relaunched, self.record()), ([], GONE))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A seat tmux no longer holds reads by why it went and what it owes; one it cannot resume is
none.

A seat the owner closed rests: `idle`, its number still the way back in, even while its plan
owes work.  One whose process went on its own (a crash, a reboot) needs the owner while it owes
work, since nothing moves it until it is opened; owing nothing it is `idle`, or `done` once its
plan is finished.  Nothing read its screen, and `ak orch why` says so.  A record with no
conversation its launcher issued is no seat at all, unless the owner closed it: that one keeps
its row, and listing it writes its word and reason into its seat file.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, beside records of
tests/fixtures/akseat.py; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

GONE = "  authority: -     the process is gone; nothing here read its screen"
OWED = "- [ ] Write the docs\n"


class GoneSeat(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def gone(self, name="acme", **fields):
        """A seat's record and nothing of it in tmux; a field given None is left out."""
        seat = Seat(self.home, name, alive=False, record={"created": int(time.time()) - 3600,
                                                          **fields})
        record = {key: value for key, value in seat.record.items() if value is not None}
        self.home.write(f".agentkit/state/session-{name}.json", record)

    def why(self, name="acme"):
        """`ak orch why`'s first line and reason, once it says nothing read the screen."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        self.assertIn(GONE, lines)
        reasons = [line.split(":", 1)[1].strip() for line in lines
                   if line.startswith("  reason:")]
        self.assertEqual(len(reasons), 1, done.out)
        return lines[0], reasons[0]

    def rows(self):
        """`ak orch list`'s rows by the seat each names."""
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        return {line.split()[0]: line for line in done.out.splitlines()[1:] if line.strip()}

    def row(self, name="acme"):
        rows = self.rows()
        self.assertIn(name, rows)
        return rows[name]

    def seat_file(self, name):
        return json.loads((self.home.path / f".agentkit/state/seat-{name}.json").read_text())

    def test_a_seat_the_owner_closed_rests_though_it_owes_work_and_its_number_reopens_it(self):
        self.gone(conversation="0b9e6c1e-4c33-4c55-9a1e-6f1d2b3c4d5e")
        self.home.write(".agentkit/state/seat-acme.json",
                        {"stopped_at": int(time.time()) - 60, "closed_by_owner": True})
        self.home.write(".agentkit/state/plan-acme.md", OWED)
        self.assertEqual(self.why(),
                         ("acme  idle", "session closed by the owner: reopen it from past sessions"))
        self.assertIn("○ idle", self.row())

    def test_a_seat_gone_on_its_own_owing_work_needs_you_whether_or_not_tmux_runs(self):
        self.gone()
        self.home.write(".agentkit/state/plan-acme.md", OWED)
        self.assertEqual(self.why(), ("acme  needs you", "session closed: press 1 to reopen"))
        self.assertIn("! needs you", self.row())
        if REAL_TMUX:
            # a server holding another seat is not this seat's session either
            Seat(self.home, "beta")
            self.assertEqual(self.why(),
                             ("acme  needs you", "session closed: press 1 to reopen"))

    def test_a_seat_gone_on_its_own_owing_nothing_rests_and_with_its_plan_finished_is_done(self):
        self.gone()
        self.assertEqual(self.why(), ("acme  idle", "session closed: press 1 to reopen"))
        self.assertIn("○ idle", self.row())
        self.home.write(".agentkit/state/plan-acme.md", "- [x] Write the docs\n")
        self.assertEqual(self.why(), ("acme  done", "Write the docs"))
        self.assertIn("✓ done", self.row())

    def test_a_record_with_no_conversation_its_launcher_issued_is_no_seat(self):
        unlisted = "no orchestrator session 'acme'"
        for case, fields in (("no conversation", {"conversation": None}),
                             ("one the launcher did not issue", {})):
            with self.subTest(case):
                self.gone(id_source=None, resumable=None, **fields)
                done = self.home.ak("orch", "why", "acme")
                self.assertEqual(done.code, 2, done.out)
                self.assertIn(unlisted, done.err)
                done = self.home.ak("orch", "list")
                self.assertEqual(done.code, 0, done.err)
                self.assertTrue(done.out.startswith("no orchestrator session;"), done.out)
        if REAL_TMUX:
            Seat(self.home, "beta")
            # a server holding another seat leaves this record no seat still
            self.assertIn(unlisted, self.home.ak("orch", "why", "acme").err)
            self.assertEqual(sorted(name for name in self.rows() if name in ("acme", "beta")),
                             ["beta"])

    def test_listing_a_seat_the_owner_closed_keeps_it_and_writes_idle_and_why_to_its_file(self):
        stopped = int(time.time()) - 30
        # no conversation to resume: the owner's close alone keeps its row
        self.gone("closed", created=int(time.time()), conversation=None, id_source=None,
                  resumable=None)
        self.home.write(".agentkit/state/seat-closed.json",
                        {"stopped_at": stopped, "closed_by_owner": True, "session": "closed"})
        self.assertIn("○ idle", self.row("closed"))
        seat = self.seat_file("closed")
        self.assertEqual((seat.get("stopped_at"), seat.get("closed_by_owner"), seat.get("word")),
                         (stopped, True, "idle"))
        self.assertTrue(seat.get("reason", "").startswith(
            "session closed by the owner: reopen it from past sessions"), seat)


if __name__ == "__main__":
    unittest.main()

"""An ending that waits for its seat's next quiet prompt is that seat's own question: its
`ak run status` reads `needs you` and points to the look by id, and that look prints the line the
tick would type and records the ending handed back, so the tick never types it as news after.

Only that seat's look by id records it: a listing can be cut before its row is read, a look whose
output never got out told nobody, and a look finding the delivery lock held, never waiting for
it, prints the line and leaves the record to the tick handing that ending back.  The owner,
another seat and `--json` read what they read before.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, the
ending's record under its HOME, the seat its name in the environment, as a seat's `ak` has it.
"""

import fcntl
import json
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

RUN = "20261028-0900-fix-the-parser"
READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}
POINTER = f"its ending waits for you: ak run status {RUN}"
LINE = re.compile(rf"^  run {RUN} finished FAIL: the parser drops the last row\. "
                  rf"Result: \S+/{RUN}/result\.md\. Decide the next step\.$", re.M)


class SeatReadsWaitingEnding(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.ended()

    def ended(self, **fields):
        """The run's record: its seat was busy as it ended, deferred and typed by nobody yet."""
        now = time.time()
        self.home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Fix the parser", "launched_session": "acme",
            "state": "fail", "verdict": "FAIL", "error": "the parser drops the last row",
            "executor": "opus", "reviewer": "astra", "rounds": 2, "round_summaries": [{}, {}],
            "started_at": now - 3600, "finished_at": now - 600, "handback_pending": True,
            **fields})

    def record(self):
        return json.loads((self.home.path / f".agentkit/runs/{RUN}/run.json").read_text())

    def status(self, *args, seat="acme"):
        done = self.home.ak("run", "status", *args, env={
            "AGENTKIT_SESSION": seat, "AK_HOST_READINGS": json.dumps(READINGS),
            "COLUMNS": "120"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def row(self, out):
        return next(line for line in out.splitlines() if line.startswith(RUN))

    def assert_waiting(self):
        said = self.record()
        self.assertTrue(said.get("handback_pending"), said)
        self.assertFalse(said.get("handed_back"), said)

    def test_its_listing_reads_needs_you_and_points_to_the_look_recording_nothing(self):
        for args in ((), ("--why",), ("--plain",)):
            out = self.status(*args)
            self.assertIn(f"\n  {POINTER}\n", out, args)
            self.assertNotRegex(out, LINE)
            if args != ("--plain",):
                self.assertIn("needs you", self.row(out), args)
        self.assert_waiting()

    def test_its_look_by_id_prints_the_line_and_the_tick_owes_it_no_more(self):
        out = self.status(RUN)
        self.assertRegex(out, LINE)
        self.assertNotIn(POINTER, out)
        said = self.record()
        self.assertNotIn("handback_pending", said)
        self.assertGreaterEqual(said["handed_back"], said["finished_at"])
        self.assertTrue(said["reported"])
        self.assertIn("ak run status", said["handback_note"])
        # said once: the next look and the listing read it as done
        self.assertNotRegex(self.status(RUN), LINE)
        listing = self.status()
        self.assertIn("done", self.row(listing))
        self.assertNotIn(POINTER, listing)

    def test_the_owner_another_seat_and_json_read_as_before(self):
        for seat in (None, "beta"):
            listing = self.status(seat=seat)
            self.assertNotIn(POINTER, listing)
            out = self.status(RUN, seat=seat)
            self.assertIn("done", self.row(out))
            self.assertNotRegex(out, LINE)
        self.assertEqual(json.loads(self.status(RUN, "--json"))[0]["handback_pending"], True)
        self.assertEqual(json.loads(self.status("--json"))[0]["handback_pending"], True)
        self.assert_waiting()

    def test_a_look_whose_output_never_got_out_records_nothing(self):
        done = self.home.run("sh", "-c", 'exec "$0" run status "$1" >/dev/full', AK, RUN,
                             env={"AGENTKIT_SESSION": "acme",
                                  "AK_HOST_READINGS": json.dumps(READINGS)})
        self.assertNotEqual(done.code, 0)
        self.assert_waiting()

    def test_a_look_meeting_the_tick_handing_it_back_prints_it_and_leaves_the_record(self):
        lock = self.home.path / f".agentkit/runs/{RUN}/delivery.lock"
        # the short line, then one too long for a composer, whose full notice goes to
        # result.md under that lock: the tick holding it saves it, and the look never waits
        long = "the parser already keeps the last row; " * 40
        compact = re.compile(rf"^  run {RUN} finished DONE\. Result: \S+/{RUN}/result\.md\. "
                             rf"Decide the next step\.$", re.M)
        for fields, line in (({}, LINE), ({"state": "not_needed", "not_needed": long}, compact)):
            self.ended(**fields)
            self.status()       # first, as the tick's pass does: its loop's leftovers swept
            with lock.open("a") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                self.assertRegex(self.status(RUN), line)
                self.assert_waiting()
            self.assertRegex(self.status(RUN), line)
            self.assertTrue(self.record()["handed_back"])
        result = self.home.path / f".agentkit/runs/{RUN}/result.md"
        self.assertIn(long.strip(), result.read_text())


if __name__ == "__main__":
    unittest.main()

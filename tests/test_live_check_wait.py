"""A merged run of a seat's whose project has yet to prove itself live is a wait ak records.

The merge records the `health:` its delivered commit declares, once, in every merge path
(`run.merge_record`); the tick keeps that record until the probe passes, and follows a run
past the after-merge window only on a probe that failed inside it; and the seat's word reads
the record as `working`, below a run parked undecided, so no card goes out while ak's own
probe is pending (`watch.awaiting_live`).  Offline: fake records in a throwaway HOME
(`fixtures.merged_run`).
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.merged_run import SEAT, MergedRuns
from agentkit import config, run, watch


class LiveCheckWait(MergedRuns):
    def word(self, session=None):
        """The seat's word off its own records alone, as every screen and the card pass read it."""
        records = [(directory, json.loads((directory / "run.json").read_text()))
                   for directory in sorted(self.runs.iterdir())]
        with patch.object(config, "STATE", self.state), patch.object(config, "RUNS", self.runs):
            return watch.session_state(SEAT, records=records, session=session or {"name": SEAT},
                                       number=1, harness="claude", live={}, auth_out={},
                                       gh_out={}, token_out=None)

    def test_a_merge_records_the_health_its_delivered_commit_declares_and_the_wait_reads_that(self):
        bare = "---\nusers: real\n---\n# acme\n"
        with_health = "---\nusers: real\nhealth: curl -fsS https://acme.test/ok\n---\n# acme\n"
        # the merge step records what the delivered commit declares, once, for the tick and the word
        wt, sha = self.delivered("declares", with_health)
        self.assertEqual(run.merge_record(wt, sha), {"health": {"command": "curl -fsS https://acme.test/ok"}})
        wt, sha = self.delivered("silent", bare)
        self.assertEqual(run.merge_record(wt, sha), {})
        self.assertEqual(run.merge_record(None, sha), {})           # no checkout at hand: the tick reads GitHub's
        # the wait reads that record and nothing else: a checkout's own file decides nothing
        self.merged("recorded", health=True, tree=bare)
        self.assertTrue(watch.awaiting_live(json.loads((self.runs / "recorded" / "run.json").read_text())))
        self.merged("tree-only", health=False, tree=with_health)
        self.assertFalse(watch.awaiting_live(json.loads((self.runs / "tree-only" / "run.json").read_text())))

    def test_the_seat_reads_working_while_its_merged_run_awaits_live(self):
        self.merged("awaits")
        answer = self.word()
        self.assertEqual(answer["word"], "working", answer)
        self.assertIn("waiting on the live check", answer["reason"])
        # ... and once the project is live, or the window is over, that run holds no word
        for name, how in (("live", {"live": True}), ("old", {"age": watch.AFTER_MERGE_WINDOW + 60})):
            with self.subTest(name):
                self.setUp()
                self.merged(name, **how)
                self.assertNotEqual(self.word()["word"], "working")
        # ... and a run parked undecided outranks it, in the stop hook's order: its card goes out
        self.setUp()
        self.merged("awaits")
        self.parked_exhausted()
        answer = self.word()
        self.assertEqual(answer["word"], "needs you", answer)
        self.assertIn("parked-exhausted", answer["reason"])
        # ... in a closed seat too, where its number is the way back to it
        answer = self.word({"name": SEAT, "exited": True})
        self.assertEqual(answer["word"], "needs you", answer)
        self.assertIn("press 1 to reopen", answer["reason"])
        # ... while with none parked, a closed seat waits on the live check all the same
        self.setUp()
        self.merged("awaits")
        self.assertEqual(self.word({"name": SEAT, "exited": True})["word"], "working")


if __name__ == "__main__":
    unittest.main()

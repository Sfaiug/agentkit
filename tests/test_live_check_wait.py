"""A merged run of a seat's whose project has yet to prove itself live is a wait ak records.

The merge records the `health:` its delivered commit declares, or that it declares none, once,
in every merge path (`watch.merge_record`); the tick keeps that record until the probe passes,
and follows a run past the after-merge window only on a probe that failed inside it; and the
seat's word reads the record as `working`, below a run parked undecided, so no card goes out
while ak's own probe is pending (`watch.awaiting_live`).  Offline: fake records in a throwaway
HOME (`fixtures.merged_run`).
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.merged_run import SEAT, MergedRuns
from agentkit import config, notify, watch


class LiveCheckWait(MergedRuns):
    def word(self, session=None):
        """The seat's word off its own records alone, as every screen and the card pass read it."""
        records = [(directory, json.loads((directory / "run.json").read_text()))
                   for directory in sorted(self.runs.iterdir())]
        with patch.object(config, "STATE", self.state), patch.object(config, "RUNS", self.runs):
            return watch.session_state(SEAT, records=records, session=session or {"name": SEAT},
                                       number=1, harness="claude", live={}, auth_out={},
                                       gh_out={}, token_out=None)

    def card_pass(self):
        """One tick's card pass over the seat, as `notify.tick_cards` runs it: its card's word."""
        home = self.home / ".agentkit"
        with ExitStack() as stack:
            for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
                stack.enter_context(patch.object(config, name, home if name == "HOME" else home / name.lower()))
            stack.enter_context(patch.dict(os.environ, {
                "HOME": str(self.home), "AK_NOTIFY_SINK": "off", "AGENTKIT_DISCORD_WEBHOOK": "off",
                "AK_RUN_ROLE": ""}))
            stack.enter_context(patch.object(notify, "post", return_value=0))
            notify.transition(SEAT, seat={"name": SEAT}, log=lambda line: None)
            return notify._card_read(SEAT).get("word")

    def test_a_merge_records_the_health_its_delivered_commit_declares_and_the_wait_reads_that(self):
        bare = "---\nusers: real\n---\n# acme\n"
        with_health = "---\nusers: real\nhealth: curl -fsS https://acme.test/ok\n---\n# acme\n"
        # the merge step records what the delivered commit declares, once, for the tick and the word
        wt, sha = self.delivered("declares", with_health)
        self.assertEqual(watch.merge_record(wt, sha), {"health": {"command": "curl -fsS https://acme.test/ok"}})
        wt, sha = self.delivered("silent", bare)
        self.assertEqual(watch.merge_record(wt, sha), {"health": {}})
        self.assertEqual(watch.merge_record(None, sha), {})         # no checkout at hand: the tick reads GitHub's
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
        # ... and a job's `all N tasks finished` is no word of the seat's: beside a run of its
        # own failed after it, the seat still waits on the live check, and no card goes out
        self.setUp()
        self.merged("awaits")
        (self.runs / "failed").mkdir()
        (self.runs / "failed" / "run.json").write_text(json.dumps(
            {"run_id": "failed", "launched_session": SEAT, "state": "fail", "verdict": "FAIL",
             "handed_back": True, "started_at": time.time() - 900, "finished_at": time.time() - 10}) + "\n")
        with patch.object(config, "STATE", self.state):
            config.notify_path(SEAT).write_text(json.dumps(
                {"session": SEAT, "kind": "done", "text": "all 3 tasks finished", "source": "job:acme",
                 "time": time.time() - 30}))
        self.assertEqual(self.word()["word"], "working")

    def test_what_is_his_below_outranks_the_wait(self):
        """A handed-back run left undecided, a run failed after the seat's done, a watcher's
        alert: each is his, so each keeps the word it reads without the wait, and keeps it once
        the card pass has read it -- a done it drops for a failed run is only marked seen."""
        undecided = {"state": "interrupted", "interruption_reason": "the host restarted",
                     "recovery_pending": True}
        for name, run_state, notice in (
                ("undecided", undecided, {"kind": "done", "text": "all shipped"}),
                ("failed", {"state": "fail", "verdict": "FAIL"}, {"kind": "done", "text": "all shipped"}),
                ("alert", None, {"kind": "needs", "text": "acme is stuck", "watcher": True})):
            with self.subTest(name):
                self.setUp()
                self.merged("awaits")
                if run_state:
                    (self.runs / name).mkdir()
                    (self.runs / name / "run.json").write_text(json.dumps(
                        {"run_id": name, "launched_session": SEAT, "handed_back": True,
                         "started_at": time.time() - 900, "finished_at": time.time() - 10,
                         **run_state}) + "\n")
                with patch.object(config, "STATE", self.state):
                    config.notify_path(SEAT).write_text(json.dumps(
                        {"session": SEAT, "time": time.time() - 30, **notice}))
                self.assertEqual(self.word()["word"], "needs you")
                self.assertEqual(self.card_pass(), "needs you")
                self.assertEqual(self.word()["word"], "needs you")


if __name__ == "__main__":
    unittest.main()

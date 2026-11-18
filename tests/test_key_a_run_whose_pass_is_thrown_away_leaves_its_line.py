"""A run whose saved PASS is thrown away leaves its line, before it asks for a slot.

A member parked in a line with a green verdict is resumed as the line resumes it, its reviewer's
mark renamed in the config meanwhile: the saved PASS can no longer be judged eligible.  Kept in
the line without its review, the run's own delivery and the lander's check of every member read
a review that was gone: twelve passed runs ended in error and two projects merged nothing for over
an hour (17 Nov 2026).  It reviews its saved work again and joins the line anew, as work a host
with no room holds back: a green delivery is let in past that only to merge.  So does one whose
review an older ak erased in the line, keeping its green place: it resumes that review.
Black-box, on the fixture of tests/test_key_a_delivering_run_has_the_landing_weight.py, whose
systemd-run renames the mark, and gives the resume its host readings, as a resume's scope starts.
"""

import json
import time
import unittest

from fixtures import taskfile
from test_key_a_delivering_run_has_the_landing_weight import Delivery

RENAMED = '''if args[-2] == "resume":
    config = pathlib.Path({root}, "home", ".agentkit", "config.toml")
    config.write_text(config.read_text().replace('"astra"', '"nova"'))
'''
# How an older ak left a green member whose PASS it threw away: the review pending, the place kept.
ERASED = '''run = pathlib.Path({root}, "home", ".agentkit", "runs", args[-1])
if args[-2] == "resume" and not pathlib.Path({root}, "erased").exists():
    import fcntl, json
    lock = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(lock, fcntl.LOCK_EX)
    state = json.loads((run / "run.json").read_text())
    if state["verdict"] == "PASS" and "land" in (state.get("waiting_on") or {{}}):
        pathlib.Path({root}, "erased").touch()
        entries = state["round_summaries"]
        state.update(verdict=None, review=None, rounds=max(state["rounds"], len(entries) + 1),
                     review_pending={{"round": len(entries) + 1, "summary": entries[-1]["summary"]}})
        (run / "run.json").write_text(json.dumps(state))
    os.close(lock)
'''
FULL = '''    del os.environ["AK_MAX_RUNS"]       # 0 turns admission off
    os.environ["AK_HOST_READINGS"] = '{{"cpus": 4, "load": 0, "free_mb": 1}}'
'''


class ARunWhosePassIsThrownAwayLeavesItsLine(Delivery, unittest.TestCase):
    starts = RENAMED

    def record(self):
        try:
            return json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        except (AssertionError, OSError, ValueError):
            return {}       # before the run has one, or as it is written

    def test_it_is_reviewed_again_and_merges(self):
        task = self.task()
        # Its exit is not read: its starter judges the record by the config from before the rename.
        self.home.ak("run", str(task), timeout=600)
        record = self.record()
        self.assertTrue(record.get("merged"), record)
        self.assertEqual(self.fakes["codex"].n, 2)

    def test_a_green_place_kept_without_its_review_is_reviewed_again_and_merges(self):
        self.starts = ERASED
        task = self.task()
        self.home.ak("run", str(task), timeout=600)
        record = self.record()
        self.assertTrue((self.home.root / "erased").exists(), record)
        self.assertTrue(record.get("merged"), record)
        # the saved work is reviewed again, never given to a fixer
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 2))

    def test_a_host_with_no_room_holds_it_back_as_work(self):
        self.starts += FULL
        task = self.task()
        run = self.home.spawn("run", str(task))
        deadline = time.monotonic() + 300
        while (record := self.record()).get("slot_wait_kind") != "memory":
            if run.poll() is not None or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        self.assertEqual(record.get("slot_wait_kind"), "memory", record)
        self.assertNotIn("waiting_on", record)
        self.assertEqual(self.fakes["codex"].n, 1)


if __name__ == "__main__":
    unittest.main()

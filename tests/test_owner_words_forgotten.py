"""A job saves no copy of the owner's words, and every collection pass removes saved ones.

Owner rule, 2 Oct, 17 Oct, 18 Oct 2026: "The owner's own words are what a job is measured against:
the orchestrator holds them whole and writes its checks from them; ak keeps no copy. Reason: handed
to each task's reviewer, they would breed false findings and carry pasted keys."

Job receipts once saved everything the owner had typed into the seat since its last job, for a
delivery check that was never built: nothing read them back, and one held a key the owner had
pasted.  A launch now saves none, and each collection pass (before every run and once a day)
takes the words and their cursor out of any receipt or seat record that still holds them, an
older install's included.

Offline: the temporary HOME and seat of test_owner_words; no systemd unit is touched.
"""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_owner_words as fixture
from agentkit import config, gc, job, record, run

KEY = "sk-acme-0000000000000000000000"
WORDS = [{"at": 20, "text": f"Build the API. Use {KEY} for the sandbox."}]


class OwnerWordsForgotten(unittest.TestCase):
    setUp = fixture.OwnerWords.setUp
    record = fixture.OwnerWords.record
    append = fixture.OwnerWords.append

    def task(self):
        path = self.root / "fix-api.md"
        path.write_text("---\nrepo: none\n---\n# Fix API\n\n## Done when\n```bash\n"
                        "python3 -c 'assert True'\n```\n")
        return path

    def saved(self, name, **fields):
        """A finished job's receipt as an earlier install wrote it."""
        directory = config.JOBS / name
        directory.mkdir(parents=True)
        receipt = {"job_id": name, "seat": "lagoon", "started_at": 30, "finished_at": 40,
                   "tasks": [{"name": "fix-api.md", "state": "merged"}], **fields}
        job.receipt_path(directory).write_text(json.dumps(receipt, indent=2))
        return directory, receipt

    def test_a_launch_saves_none_of_the_owners_words(self):
        self.append(fixture.prompt(20, WORDS[0]["text"]))
        directory, receipt = job.job_create(self.cfg, [str(self.task())], {"--anyway": True}, None)
        self.assertEqual(receipt["seat"], "lagoon")
        self.assertNotIn(KEY, job.receipt_path(directory).read_text())
        self.assertFalse({"owner_words", "owner_words_cursor"} & job.read_job(directory).keys())
        self.assertNotIn("owner_words_cursor", self.record())

    def test_a_collection_pass_takes_saved_words_out(self):
        held, receipt = self.saved("20261012-acme-held", owner_words=WORDS,
                                   owner_words_cursor={"at": 30, "count": 1})
        clean, _ = self.saved("20261013-acme-clean")
        untouched = job.receipt_path(clean).read_bytes()
        config.update_session("lagoon", owner_words_cursor={"at": 30, "count": 1})
        said = []
        with patch.object(gc, "gc_candidates", return_value=[]):
            gc.gc(said.append)
        self.assertNotIn(KEY, job.receipt_path(held).read_text())
        kept = {key: value for key, value in receipt.items()
                if key not in ("owner_words", "owner_words_cursor")}
        self.assertEqual(job.read_job(held), kept)
        self.assertEqual(job.receipt_path(clean).read_bytes(), untouched)
        self.assertNotIn("owner_words_cursor", self.record())
        self.assertIn(f"gc: removed the owner's saved words from job {held.name}", said)

    def test_a_run_takes_them_out_before_it_starts_on_a_disk_with_room(self):
        held, _ = self.saved("20261012-acme-held", owner_words=WORDS)
        directory = config.RUNS / "20261018-fix-api"
        directory.mkdir(parents=True)
        with patch.object(gc, "disk_pressure", return_value=None), \
                patch.object(run, "history_start"), \
                patch.object(run, "task_repo", side_effect=StopIteration("work starts")):
            with self.assertRaisesRegex(StopIteration, "work starts"):
                run.loop(self.cfg, directory, self.task(), {}, lambda _: None)
        self.assertNotIn(KEY, job.receipt_path(held).read_text())

    def test_what_collection_cannot_prove_its_own_stays_and_the_rest_goes_on(self):
        victim = self.root / "owner-notes.txt"
        victim.write_text("the owner's own notes\n")
        linked, _ = self.saved("20261010-acme-linked", owner_words=WORDS)
        (linked / "job.tmp").symlink_to(victim)
        hard, _ = self.saved("20261011-acme-hard", owner_words=WORDS)
        os.link(victim, hard / "job.tmp")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        job.receipt_path(elsewhere).write_text(json.dumps({"owner_words": WORDS}))
        (config.JOBS / "20261012-acme-elsewhere").symlink_to(elsewhere, target_is_directory=True)
        unusable, _ = self.saved("20261013-acme-unusable", owner_words=WORDS)
        (unusable / record.RECOVERY_LOCK).mkdir()
        held, _ = self.saved("20261014-acme-held", owner_words=WORDS)
        config.update_session("lagoon", owner_words_cursor={"at": 30, "count": 1})
        config.session_path("lagoon").with_suffix(".tmp").symlink_to(victim)
        (config.STATE / "session- lagoon.json").write_text(json.dumps({"owner_words_cursor": {}}))
        with patch.object(gc, "gc_candidates", return_value=[]) as planner:
            gc.gc(lambda _: None)
        self.assertEqual(victim.read_text(), "the owner's own notes\n")
        for directory in (linked, hard, elsewhere, unusable):
            self.assertIn(KEY, job.receipt_path(directory).read_text())
        self.assertNotIn(KEY, job.receipt_path(held).read_text())
        self.assertIn("owner_words_cursor", self.record())
        planner.assert_called_once()


if __name__ == "__main__":
    unittest.main()

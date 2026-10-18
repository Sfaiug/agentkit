"""A job saves no copy of the owner's words, and every collection pass removes saved ones.

Job receipts once saved everything the owner had typed into the seat since its last job, for a
delivery check that was never built: nothing read them back, and one held a key the owner had
pasted.  A launch now saves none, and each collection pass (before every run and once a day)
takes the words and their cursor out of any receipt or seat record that still holds them, an
older install's included.

Offline: the temporary HOME and seat of test_owner_words; no systemd unit is touched.
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_owner_words as fixture
from agentkit import config, gc, job

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


if __name__ == "__main__":
    unittest.main()

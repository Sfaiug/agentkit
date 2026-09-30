"""Two tasks that share only a general check are not refused as the same work.

`already_under_way` read any shared test file as the same job, so two unrelated
tasks that both ran a docs check refused each other, and every task touching docs
needed `--anyway`.  A test file that at least three other jobs of the repository
named too, jobs whose titles do not name it, is a general check: sharing it alone
refuses nothing.  A test file only the jobs changing its behaviour name still
refuses as before, and a queued receipt counts as a job like any other run.

Offline: a temporary HOME with fabricated run records and a throwaway git
repository; a live rival carries this process's own identity, as test_v5ad does.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


class GeneralChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".generic-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1"}))
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, timeout=60)

    def record(self, name, title, cmds, live=False, stub=False):
        """A run of acme on disk: a live one is in flight, the rest are finished.

        stub=True is a queued receipt: its repo and title are only in its task.md.
        """
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(
            f"---\nrepo: {self.repo}\n---\n# {title}\n\n## Done when\n```bash\n"
            + "\n".join(cmds) + "\n```\n")
        state = ({"state": "queued" if stub else "running", **run.process_owner()}
                 if live or stub else {"state": "pass", "pid": 99999999})
        if not stub:
            state.update(title=title, repo=str(self.repo))
        run.save_state(directory, {"run_id": name, "started_at": time.time() - 60, **state})

    def rivals(self, title, cmds):
        return run.already_under_way(self.root / "task.md", {"repo": str(self.repo)},
                                     title, cmds)

    def past(self, test, titles=("Add export button", "Rename billing page",
                                 "Explain the retry flag"), stub=False):
        """Earlier jobs of acme that each ran `test`: finished, or queued receipts."""
        for n, title in enumerate(titles):
            self.record(f"20260901-100{n}-past", title, [f"python3 {test}"], stub=stub)

    def test_shared_general_check_starts(self):
        self.past("tests/test_docs.py")
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"], live=True)
        self.assertEqual(self.rivals("Search ignores accents",
                                     ["python3 tests/test_search.py",
                                      "python3 tests/test_docs.py"]), [])

    def test_behaviour_test_still_refuses_beside_a_general_check(self):
        self.past("tests/test_docs.py")
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"], live=True)
        rivals = self.rivals("Invoice totals show the currency",
                             ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"])
        self.assertEqual([r["id"] for r in rivals], ["20260930-1200-invoice"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice.py"])

    def test_queued_receipts_count_as_jobs(self):
        self.past("tests/test_docs.py", stub=True)
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_docs.py"], live=True)
        self.assertEqual(self.rivals("Search ignores accents",
                                     ["python3 tests/test_docs.py"]), [])

    def test_jobs_naming_the_file_never_make_it_general(self):
        """Three earlier invoice-rounding tasks change what the file checks."""
        self.past("tests/test_invoice_rounding.py", ("Invoice rounding keeps half cents",
                                                     "Round invoice lines before the total",
                                                     "Credit notes round like invoices"))
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice_rounding.py"], live=True)
        rivals = self.rivals("Fix invoice rounding precision",
                             ["python3 tests/test_invoice_rounding.py"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice_rounding.py"])

    def test_both_titles_naming_the_file_refuse_however_general(self):
        self.past("tests/test_invoice_rounding.py")
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice_rounding.py"], live=True)
        rivals = self.rivals("Fix invoice rounding precision",
                             ["python3 tests/test_invoice_rounding.py"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice_rounding.py"])

    def test_a_longer_word_is_not_the_file_subject(self):
        """`allow` does not name test_all.py, so these jobs make it a general check."""
        self.past("tests/test_all.py", ("Allow empty exports", "Allow custom avatars",
                                        "Allow keyboard navigation"))
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_all.py"], live=True)
        self.assertEqual(self.rivals("Search ignores accents",
                                     ["python3 tests/test_all.py"]), [])

    def test_one_job_relaunched_is_not_a_general_check(self):
        """Retries of one task under its own title count once, not as three jobs."""
        self.past("tests/test_invoice.py", ["Half cents go to the customer"] * 3)
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py"], live=True)
        rivals = self.rivals("Invoice totals show the currency",
                             ["python3 tests/test_invoice.py"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice.py"])

if __name__ == "__main__":
    unittest.main(verbosity=2)

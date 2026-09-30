"""Two tasks that share only a general check are not refused as the same work.

`already_under_way` read any shared test file as the same job, so two unrelated
tasks that both ran a docs check refused each other, and every task touching docs
needed `--anyway`.  A test file that at least three other jobs of the repository
named too is a general check: sharing it alone refuses nothing.  A test file only
the jobs changing its behaviour name still refuses as before.

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

    def record(self, name, title, cmds, live=False):
        """A run of acme on disk: a live one is in flight, the rest are finished."""
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(
            f"---\nrepo: {self.repo}\n---\n# {title}\n\n## Done when\n```bash\n"
            + "\n".join(cmds) + "\n```\n")
        state = ({"state": "running", **run.process_owner()} if live
                 else {"state": "pass", "pid": 99999999})
        run.save_state(directory, {"run_id": name, "title": title, "repo": str(self.repo),
                                   "started_at": time.time() - 60, **state})

    def rivals(self, title, cmds):
        return run.already_under_way(self.root / "task.md", {"repo": str(self.repo)},
                                     title, cmds)

    def test_shared_general_check_starts(self):
        for n, title in enumerate(("Add export button", "Rename billing page",
                                   "Explain the retry flag")):
            self.record(f"20260901-100{n}-past", title, ["python3 tests/test_docs.py"])
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"], live=True)
        self.assertEqual(self.rivals("Search ignores accents",
                                     ["python3 tests/test_search.py",
                                      "python3 tests/test_docs.py"]), [])

    def test_behaviour_test_still_refuses_beside_a_general_check(self):
        for n, title in enumerate(("Add export button", "Rename billing page",
                                   "Explain the retry flag")):
            self.record(f"20260901-100{n}-past", title, ["python3 tests/test_docs.py"])
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"], live=True)
        rivals = self.rivals("Invoice totals show the currency",
                             ["python3 tests/test_invoice.py", "python3 tests/test_docs.py"])
        self.assertEqual([r["id"] for r in rivals], ["20260930-1200-invoice"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice.py"])

    def test_one_job_relaunched_is_not_a_general_check(self):
        """Retries of one task under its own title count once, not as three jobs."""
        for n in range(3):
            self.record(f"20260901-100{n}-retry", "Invoices round to cents",
                        ["python3 tests/test_invoice.py"])
        self.record("20260930-1200-invoice", "Invoices round to cents",
                    ["python3 tests/test_invoice.py"], live=True)
        rivals = self.rivals("Invoice totals show the currency",
                             ["python3 tests/test_invoice.py"])
        self.assertEqual(rivals[0]["files"], ["tests/test_invoice.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

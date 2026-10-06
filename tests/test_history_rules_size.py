"""Each run's history row keeps the size of the AGENTS.md its workers were handed, and
`ak run status --history` shows a repository's latest against the most a harness reads of it.

The size is the ceiling's own measure: the bytes a checkout holds at the run's base, Git's
line-end conversion applied, so the number shown and the number the ceiling refuses are one.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, run, status  # noqa: E402


class RulesSize(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agentkit-rules-size-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        home = self.root / ".agentkit"
        home.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(config, "HOME", home).start()
        patch.object(config, "RUNS", home / "runs").start()
        self.addCleanup(history._OPEN.clear)
        self.acme = self.root / "acme"
        self.git(self.root, "init", "-q", "-b", "main", str(self.acme))

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=Acme", "-c",
                               "user.email=acme@example.com", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git(self.acme, "add", "-A")
        self.git(self.acme, "commit", "-qm", message)
        return self.git(self.acme, "rev-parse", "HEAD")

    def finish(self, run_id, base, finished_at):
        history.start_run(run_id, repo=str(self.acme), started_at=finished_at - 10)
        run.history_finish({"run_id": run_id, "repo": str(self.acme), "worktree": str(self.acme),
                            "base_sha": base, "state": "pass", "verdict": "PASS",
                            "started_at": finished_at - 10, "finished_at": finished_at})
        return history.get(run_id)["rules_bytes"]

    def test_a_run_keeps_the_bytes_a_checkout_held_at_its_base(self):
        # stored with LF, checked out with CRLF: a harness reads the checkout's bytes
        (self.acme / ".gitattributes").write_text("AGENTS.md text eol=crlf\n")
        (self.acme / "AGENTS.md").write_text("# Acme\n\nShip small.\n")
        base = self.commit("rules")
        handed = len("# Acme\r\n\r\nShip small.\r\n")
        # the branch grows the file; its workers were handed the base's
        (self.acme / "AGENTS.md").write_text("# Acme\n\nShip small.\nTest first.\n")
        self.commit("more rules")
        self.assertEqual(self.finish("r1", base, 100), handed)
        self.assertEqual(len(run.rules_bytes(self.acme, base)), handed)

    def test_no_file_and_a_link_record_nothing(self):
        (self.acme / "README.md").write_text("acme\n")
        none = self.commit("no rules")
        self.assertIsNone(self.finish("r1", none, 100))
        os.symlink("docs/rules.md", self.acme / "AGENTS.md")
        linked = self.commit("linked rules")
        self.assertIsNone(self.finish("r2", linked, 200))

    def test_the_history_line_shows_the_latest_size_against_the_ceiling(self):
        for run_id, size, finished in (("older", 1000, 100), ("newer", 2000, 200)):
            history.start_run(run_id, repo="acme", started_at=finished - 10)
            history.finish_run(run_id, repo="acme", started_at=finished - 10,
                               finished_at=finished, final_state="pass", verdict="PASS",
                               rounds_used=1, rules_bytes=size)
        history.start_run("plain", repo="plainco", started_at=90)
        history.finish_run("plain", repo="plainco", started_at=90, finished_at=100,
                           final_state="pass", verdict="PASS", rounds_used=1)
        with patch.object(config, "instruction_ceiling", return_value=(32768, "codex")):
            self.assertTrue(status.size_summary_line("acme").endswith(
                " · AGENTS.md 2,000 bytes of 32,768"))
            self.assertNotIn("AGENTS.md", status.size_summary_line("plainco"))
        with patch.object(config, "instruction_ceiling", return_value=None):
            self.assertTrue(status.size_summary_line("acme").endswith(" · AGENTS.md 2,000 bytes"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

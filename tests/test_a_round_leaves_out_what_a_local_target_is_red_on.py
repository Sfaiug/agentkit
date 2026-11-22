"""A round whose target origin has no branch of leaves out the tests the target's landing line
holds red on the commit its run is based on: the local branch's as the run started, though that
branch has moved with the work since.

In-process on a sandbox HOME (tests/fixtures/sandbox.py), with real Git; the landings' reds are
injected, and the line's record is written as its lander writes it.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import deliver, gitcall, history, land, round_tests, suite_times

# By landings held runs first; the record times both.
REDS = {"held": {"landings": 2}, "often": {"landings": 1}}
TIMES = "PASS  held (1.0s)\nPASS  often (1.0s)\n"


class ARound(Sandbox):
    def test_it_leaves_out_what_the_line_holds_its_base_red_on(self):
        repo = self.root / "acme"
        repo.mkdir()
        gitcall.git(repo, "init", "-q")
        (repo / "AGENTS.md").write_text("---\ntests: sh suite.sh\n---\n")
        # The base, then the work on the same branch: no remote, so no `origin/main`.
        for files in (("held", "often"), ("work",)):
            for name in files:
                (repo / name).write_text("")
            gitcall.git(repo, "add", ".")
            gitcall.git(repo, "-c", "user.name=Acme", "-c", "user.email=acme@localhost",
                        "commit", "-qm", "acme")
        measured = self.root / "measured.log"
        measured.write_text(TIMES)
        suite_times.keep(repo, measured)
        lp = SimpleNamespace(wt=repo, state={"repo": str(repo), "worktree": str(repo)},
                             scratch=False, upstream="origin/main",
                             base_sha=gitcall.git(repo, "rev-parse", "HEAD^"))
        land.note(deliver.turn_path(lp, lp.upstream), [], "fix-api", red={
            gitcall.git(repo, "rev-parse", "HEAD^^{tree}"): {"tests": ["held"]}})
        with patch.object(history, "test_audit", return_value=(REDS, None, 1)):
            self.assertEqual(round_tests.chosen(lp)[1], ["often"])


if __name__ == "__main__":
    unittest.main()

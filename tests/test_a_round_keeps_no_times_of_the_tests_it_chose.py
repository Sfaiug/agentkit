"""A round's check of the tests it chose from the time record keeps none of their times, so a
resumed round chooses the same tests from the same record.  Its re-run, handed the tests less a part
its tree lacks, measures the rest anew: kept, those times would change what fits in the piece.

In-process on a sandbox HOME (tests/fixtures/sandbox.py), with real Git and a suite of its own;
the landings' reds and the piece's seconds are injected.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import gitcall, history, round_tests, roundloop, suite_times, worker

# Names a handed part ending `::gone` as not there and failed, as tests/every_file.py does, the
# rest as run, timing each at 3 s, and exits 1 for a part not there.
SUITE = """grep -x '.*::gone' "$AK_ONLY" >"$AK_NOT_THERE"
cp "$AK_NOT_THERE" "$AK_FAILED"
grep -vx '.*::gone' "$AK_ONLY" >"$AK_RAN"
sed 's/.*/PASS  & (3.0s)/' "$AK_RAN"
! [ -s "$AK_NOT_THERE" ]
"""
# In a piece of 3 s, by landings: parts::gone and slow fit, then next does not; slow timed at 3 s,
# next would.
TIMES = "PASS  parts::gone (1.0s)\nPASS  slow (1.0s)\nPASS  next (2.0s)\n"
REDS = {"parts::gone": {"landings": 3}, "slow": {"landings": 2}, "next": {"landings": 1}}


class ARound(Sandbox):
    def test_its_chosen_tests_keep_no_times(self):
        repo = self.root / "acme"
        repo.mkdir()
        for name, text in (("AGENTS.md", '---\ntests: : "$AK_SHARD"; sh suite.sh\n---\n'),
                           ("suite.sh", SUITE), ("parts", ""), ("slow", ""), ("next", "")):
            (repo / name).write_text(text)
        gitcall.git(repo, "init", "-q")
        gitcall.git(repo, "add", ".")
        gitcall.git(repo, "-c", "user.name=Acme", "-c", "user.email=acme@localhost", "commit",
                    "-qm", "acme")
        measured = self.root / "measured.log"
        measured.write_text(TIMES)
        suite_times.keep(repo, measured)
        head = gitcall.git(repo, "rev-parse", "HEAD")
        lp = SimpleNamespace(wt=repo, run_dir=self.root, round_dir=self.root, done_when_limit=60,
                             turn_limit=30, rnd=1, state={"repo": str(repo), "target_sha": head},
                             scratch=False, upstream="HEAD", base_sha=head, artifacts=set(),
                             step=lambda _: None, log=lambda _: None)
        with patch.object(history, "test_audit", return_value=(REDS, 3, 1)), \
                patch.object(worker, "kill_marked"), patch.object(roundloop, "rebase_for_review"):
            chosen = round_tests.chosen(lp)
            self.assertEqual(chosen[1], ["parts::gone", "slow"])
            ok, text = roundloop.verify_work(lp, [])
            self.assertTrue(ok, text)
            self.assertEqual(suite_times.read(suite_times.handed(repo)),
                             {"parts::gone": 1.0, "slow": 1.0, "next": 2.0})
            self.assertEqual(round_tests.chosen(lp), chosen)


if __name__ == "__main__":
    unittest.main()

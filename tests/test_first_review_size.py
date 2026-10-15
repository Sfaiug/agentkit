"""Each run's history row keeps the size its first review read, whatever its ending.

The size is the first-review ceiling's own measure, taken at the commit round 1 reviewed over
the base its reviewer diffed against, however landing moved the run's base since: the added
lines, generated files aside, less the blocks moved unchanged from lines the diff deletes.
A run that failed or was blocked keeps it as a merged one does, so the scoreboard can weigh
round-1 passes, landings and review by size without counting only the runs that got through.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import BRANCH, OwnPr  # noqa: E402
from agentkit import config, history, run  # noqa: E402


class FirstReviewSize(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agentkit-first-review-size-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        home = self.root / ".agentkit"
        home.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(config, "HOME", home).start()
        patch.object(config, "RUNS", home / "runs").start()
        patch.object(config, "TMP", self.root).start()     # the private index's home
        self.addCleanup(history._OPEN.clear)
        self.acme = self.root / "acme"
        self.acme.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.acme / ".gitattributes").write_text("dist/* linguist-generated\n")
        (self.acme / "old.py").write_text("".join(f"value_{n} = {n} * 1000\n" for n in range(30)))
        self.base = self.commit("Base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.acme), "-c", "user.name=Acme", "-c",
                               "user.email=acme@example.com", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def finish(self, run_id, state, summaries):
        history.start_run(run_id, repo=str(self.acme), started_at=90)
        run.history_finish({"run_id": run_id, "repo": str(self.acme), "worktree": str(self.acme),
                            # landing moved the run's base onto what it reviewed
                            "base_sha": self.git("rev-parse", "HEAD"),
                            "verdict": state.upper(), "state": state,
                            "round_summaries": summaries, "started_at": 90, "finished_at": 100})
        return history.get(run_id)["first_review_lines"]

    def test_every_ending_keeps_the_lines_its_first_review_read(self):
        # round 1 reads 12 new lines, a generated file and old.py moved whole into a new home
        (self.acme / "dist").mkdir()
        (self.acme / "dist/app.js").write_text("built\n" * 50)
        (self.acme / "new.py").write_text("".join(f"fresh_{n} = {n}\n" for n in range(12)))
        (self.acme / "lib").mkdir()
        (self.acme / "old.py").rename(self.acme / "lib/kept.py")
        first = self.commit("Round 1")
        # the fix round adds more; the first review read none of it
        (self.acme / "fix.py").write_text("".join(f"fix_{n} = {n}\n" for n in range(40)))
        second = self.commit("Round 2")
        summaries = [{"round": 1, "verdict": "FAIL", "base_sha": self.base, "head_sha": first},
                     {"round": 2, "verdict": "FAIL", "base_sha": self.base, "head_sha": second}]
        for ending in ("fail", "blocked", "pass"):
            with self.subTest(ending=ending):
                self.assertEqual(self.finish(f"r-{ending}", ending, summaries), 12)

    def test_a_run_with_no_reviewed_commit_keeps_no_size(self):
        self.assertIsNone(self.finish("r-no-round", "blocked", []))
        self.assertIsNone(self.finish("r-scratch", "pass", [{"round": 1, "verdict": "PASS"}]))
        # a commit the repository no longer holds leaves the size unknown and the ending recorded
        self.assertIsNone(self.finish("r-gone", "fail", [{"round": 1, "base_sha": self.base,
                                                          "head_sha": "f" * 40}]))
        self.assertEqual(history.get("r-gone")["final_state"], "fail")


class ReviewedRound(OwnPr):
    """Through a real own-PR review: a round a reviewer read names the base it diffed against,
    and a text-only head, passed with no reviewer, names none."""

    def finished(self, state):
        self.addCleanup(history._OPEN.clear)
        history.start_run(state["run_id"], repo=str(self.repo))
        run.history_finish(state)
        return history.get(state["run_id"])["first_review_lines"]

    def test_the_first_reviewed_round_keeps_its_size(self):
        # round 1 reads the one line of the first head; the fix round's 5000 are not its
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertEqual(self.finished(state), 1)

    def test_a_text_only_round_keeps_no_size(self):
        self.git("checkout", "-qb", "notes", "main")
        (self.repo / "notes.md").write_text("note\n" * 500)
        self.git("add", "notes.md")
        self.git("commit", "-qm", "Notes")
        self.git("push", "-q", "--force", "origin", f"{self.git('rev-parse', 'HEAD')}:refs/heads/{BRANCH}")
        state = self.review([])
        self.assertTrue(state["review"]["skipped"])
        self.assertIsNone(self.finished(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)

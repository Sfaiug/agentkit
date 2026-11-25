"""A project's numbers come from one read of its AGENTS.md on the default branch: one git
started by `config.policy`, which every prompt of every seat asks, and so no fetch moving the
branch between reads to combine two commits' numbers into a pair neither declared; and a seat's
rulebook takes those numbers and its project's text from one commit of it."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.gitrig import Rig
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, gitcall

FIRST = {"review_rounds": 3, "executor_lines": 100, "orchestrator_lines": 50, "extra_rounds": 1,
         "rescope_findings": 4}
SECOND = {"review_rounds": 3, "executor_lines": 300, "orchestrator_lines": 200, "extra_rounds": 0,
          "rescope_findings": 0}


def front(numbers):
    return {"AGENTS.md": "---\n" + "".join(f"{key}: {value}\n" for key, value in numbers.items())
                         + "---\nA project.\n"}


class OneCommit(unittest.TestCase):
    def test_the_numbers_cost_one_read(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"], settings={"review_rounds": 5})
            rig = Rig(home, "widgets", files=front(FIRST))
            rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            rig.commit(front(SECOND), "more lines", push=False)     # not the default branch's
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True), \
                    patch.object(gitcall, "git", wraps=gitcall.git) as git:
                self.assertEqual(config.policy(rig.path), FIRST)
            self.assertEqual(git.call_count, 1)

    def test_a_rulebook_takes_its_numbers_and_its_text_from_one_commit(self):
        with Home() as home:
            rig = Rig(home, "widgets", files=front(FIRST))
            second = rig.commit({"AGENTS.md": front(SECOND)["AGENTS.md"].replace("A project.",
                                                                                  "Rules two.")},
                                "more lines", push=False)
            home.write(".agentkit/state/session-seat.json",
                       {"orchestrator": "opus", "workers": ["opus"], "repo": str(rig.path)})
            read = gitcall.git

            def fetched_after(repo, verb, *args, **kw):     # a fetch lands after every read
                output = read(repo, verb, *args, **kw)
                if verb in ("show", "ls-tree", "cat-file"):
                    rig.git("update-ref", "refs/remotes/origin/main", second)
                return output
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True), \
                    patch.object(gitcall, "git", fetched_after):
                book = config.seat_rulebook("seat")
            self.assertIn("you build at most 50 added lines", book)
            self.assertIn("A project.", book)
            self.assertNotIn("Rules two.", book)


if __name__ == "__main__":
    unittest.main()

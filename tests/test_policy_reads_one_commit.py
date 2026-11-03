"""A project's three numbers come from one commit: a fetch moving the default branch between the
reads of `config.policy` must not combine two commits' numbers into a pair neither declared."""

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

FIRST = {"review_rounds": 3, "executor_lines": 100, "orchestrator_lines": 50}
SECOND = {"review_rounds": 3, "executor_lines": 300, "orchestrator_lines": 200}


def front(numbers):
    return {"AGENTS.md": "---\n" + "".join(f"{key}: {value}\n" for key, value in numbers.items())
                         + "---\nA project.\n"}


class OneCommit(unittest.TestCase):
    def test_a_fetch_between_the_reads_mixes_nothing(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"], settings={"review_rounds": 5})
            rig = Rig(home, "widgets", files=front(FIRST))
            rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            tip = rig.commit(front(SECOND), "more lines", push=False)
            reads, read = [], gitcall.declared_at

            def fetch_after_the_first(checkout, ref, key, **kw):
                value = read(checkout, ref, key, **kw)
                reads.append(key)
                if len(reads) == 1:
                    rig.git("update-ref", "refs/remotes/origin/main", tip)
                return value

            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True), \
                    patch.object(gitcall, "declared_at", side_effect=fetch_after_the_first):
                self.assertEqual(config.policy(rig.path), FIRST)


if __name__ == "__main__":
    unittest.main()

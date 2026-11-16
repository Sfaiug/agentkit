"""A seat's prompt starts at most four gits for its project: three for the rules its AGENTS.md
holds on the default branch, one for its numbers.

Every prompt of every seat asks whether its rulebook changed, and what it has to say waits for
the answer.  The numbers alone once took seven gits, one for each name a number goes by: ten in
all, 0.3 to 0.6 s of every prompt on a loaded host.  Black-box: Claude's hooks as the adapter
beside the program `AK_BIN` names registers them, fired from outside through
tests/fixtures/hookdrive.py, with a `git` first on its PATH that writes down each start, then
answers as git does.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, Home
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))
CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"


def front(lines):
    return {"AGENTS.md": f"---\nexecutor_lines: {lines}\n---\nA project.\n"}


class APromptStartsFourGitsForItsProject(unittest.TestCase):
    def test_the_default_branch_s_numbers_reach_the_seat_for_four_gits(self):
        with Home() as home:
            rig = Rig(home, "widgets", files=front(120))
            rig.commit(front(140), "more lines", push=False)    # not the default branch's
            hooks = Hooks(home)
            home.write(".agentkit/state/session-acme.json",
                       {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                        "cwd": str(rig.path), "repo": str(rig.path), "conversation": CONVERSATION,
                        "id_source": "launcher", "resumable": True})
            starts = home.log("git")
            home.fake("git", f"#!/bin/sh\necho >>{shlex.quote(str(starts))}\n"
                             f'exec {shlex.quote(GIT)} "$@"\n')
            fired = hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                               seat="acme")
            self.assertEqual(fired.code, 0, fired.err)
            # the seat holds no rulebook ak knows, so the prompt names the file of the whole one
            told = (home.path / ".agentkit/state/change-acme.md").read_text()
            self.assertIn("at most 120 added lines", told)
            self.assertLessEqual(len(starts.read_text().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()

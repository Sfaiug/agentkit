"""A round whose target origin has no branch of leaves out the tests that target's landing line
holds its local branch red on as the run started, though the work has moved that branch since.
It runs one the line holds red on the tree of the run's base, where a tag named as origin's
branch would be stands too.

A task run with `--no-worktree` through `bin/ak` in a Home of tests/fixtures/akbin.py, on the
origin of gitrig.py with scripted harnesses from fakeadapter.py.  The test writes an earlier
landing's reds and the line's record as ak writes them, and the suite notes the tests it was
handed to notes.py.
"""

from contextlib import closing
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_round_runs_its_changes_tests import SUITE
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, deliver, history, land

# An earlier landing was red on both; `draft` breaks the first.
BROKEN, SOUND = "./tests/broken.sh", "./tests/sound.sh"


class ARound(unittest.TestCase):
    def test_it_leaves_out_what_the_line_holds_the_local_branch_red_on_as_the_run_started(self):
        with Home() as home, closing(Notes()) as said:
            rig = Rig(home, "acme", files={
                "AGENTS.md": "---\nusers: none\nhealth: none\ntests: python3 suite.py\n---\n",
                "suite.py": SUITE.format(said=said.address), "value": "good\n",
                BROKEN: "grep -qx good value\n", SOUND: "true\n"})
            rig.git("config", "ak.repository", "0123456789ab")
            home.write(".agentkit/state/test-times-0123456789ab.json", {BROKEN: 1, SOUND: 1})
            # The base `main`, where the tag stands too, and the target `draft`, origin has no
            # branch of: the checkout is on it, so the run's commit moves that name.
            rig.git("tag", "origin/draft")
            rig.branch("draft", {"value": "bad\n"}, push=False)
            rig.git("checkout", "-q", "draft")
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                history.start_run("fix-api", repo=rig.name)
                history.test_reds(("fix-api", None, "landing", "tree"),
                                  {"failed": [BROKEN, SOUND]}, [])
                turn = deliver.merge_lock_path(rig.git("remote", "get-url", "origin"),
                                               "origin/draft")
                turn.parent.mkdir(parents=True, exist_ok=True)
                land.note(turn, [], "fix-api", red={
                    rig.git("rev-parse", "main^{tree}"): {"tests": [SOUND]},
                    rig.git("rev-parse", "draft^{tree}"): {"tests": [BROKEN]}})
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude={"write": {"retry.txt": "ok\n"}, "commit": "retry",
                                              "hand_in": [["done"]]}, codex="pass")
            task = taskfile.write(home, rig.path, front={"base": "main", "target": "draft"})
            done = home.ak("run", str(task), "--rounds", "1", "--no-worktree", "--no-merge",
                           cwd=rig.path, timeout=240)
            self.assertEqual((done.code, said.since()), (0, ["suite " + SOUND]), done.out[-900:])


if __name__ == "__main__":
    unittest.main()

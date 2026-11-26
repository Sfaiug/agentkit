"""A seat saved with no builder is told to split a PR too big for it, never to write a task.

`ak run <task>` refuses a seat whose record marks no builder (`workers: []`), so where its
branch adds more than `orchestrator_lines`, the gh guard at `gh pr create` and `ak run
--review-pr` of its own PR refuse it as executors off does, though the host's executor_lines is
not 0: "Split it into smaller PRs."  A seat with a builder is told to write it as a task.
Black-box: install.sh of the checkout `AK_BIN` names installs it in a Home, as
tests/test_key_seat_pr_size_at_create.py does, so the seat's `gh` is the installed shim, and
the real gh behind it tests/fixtures/fakegh.py's GitHub, which keeps every call it gets.
"""

import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, installer
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SPLIT = "Split it into smaller PRs."


class NoBuilderSplits(unittest.TestCase):
    def refusals(self, workers):
        """What `gh pr create` and `ak run --review-pr` say, both refused, to a seat marking
        `workers` whose branch adds 3 lines where the seat builds at most 2."""
        home = Home()
        self.addCleanup(home.close)
        installer.prepare(home)
        installed = installer.run(home)
        self.assertEqual(installed.code, 0, installed.err)
        akconfig.write(home, ["opus", "astra"], settings={"orchestrator_lines": 2})
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: none\nhealth: none\n"
                                                       "users: none\n---\nA project.\n"})
        gh = GitHub(home)
        Seat(home, "acme", cwd=rig.path, alive=False, planned=True,
             record={"workers": workers, "reviewers": ["opus"]})
        rig.branch("grow", {"grow.txt": "row\n" * 3})
        seat = {"AGENTKIT_SESSION": "acme"}
        path = os.pathsep.join([str(home.path / ".agentkit/bin"), home.env["PATH"]])
        created = home.run("gh", "pr", "create", "--fill", "--head", "grow", cwd=rig.path,
                           env={**seat, "PATH": path}, timeout=60)
        self.assertNotEqual(created.code, 0, created.out + created.err)
        self.assertEqual(home.calls("gh"), [])
        url = gh.open_pr(rig, "grow", title="Grow")
        reviewed = home.ak("run", "--review-pr", url, "--no-merge", cwd=rig.path, env=seat,
                           timeout=300)
        self.assertNotEqual(reviewed.code, 0, reviewed.out + reviewed.err)
        for said in (created.err, reviewed.err):
            self.assertIn("at most 2 added lines", said)
        return created.err, reviewed.err

    def test_a_seat_with_no_builder_is_told_to_split(self):
        for said in self.refusals([]):
            self.assertTrue(said.rstrip().endswith(SPLIT), said)

    def test_a_seat_with_a_builder_is_told_to_write_a_task(self):
        created, reviewed = self.refusals(["opus"])
        self.assertIn("Write it as a task; `from: grow` keeps what was built.", created)
        self.assertIn("Write it as a task and launch it; a worker builds it", reviewed)
        for said in (created, reviewed):
            self.assertNotIn(SPLIT, said)


if __name__ == "__main__":
    unittest.main()

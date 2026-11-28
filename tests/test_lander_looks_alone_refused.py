"""A change of looks alone whose own verdict its record refuses stacks nothing behind it.

Offline, in process, as tests/test_lander.py: a member of looks alone (`land._looks`) whose record
changes while its `# once` commands run gets no verdict this pass, and the members behind it are
checked on the target alone, never on its refused tree.  Each member's review ran its chosen tests
green on its head, as a reviewer's PASS runs them.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import SUITE, LanderFixture
from agentkit import config, gitcall, land, record, run

IMAGE = {"site.png": "teal\n"}


class ARefusedLooksVerdict(LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # work.txt, which every fixture member writes, is the target's already: a member's
        # change is the files it names alone
        (self.repo / "work.txt").write_text("work\n")
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\nhealth: true\ndeployed: true\n---\n")
        self.commit("rules")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        (config.STATE / f"test-times-{gitcall.repository_id(self.repo)}.json").write_text(
            '{"t/ok.sh": 1}')
        self.moved = None

    def member(self, name, *args, **kw):
        directory = super().member(name, *args, **kw)
        with record.record(directory) as current:
            current["review"] = {**current["review"], "chosen_passed": True}
        return directory

    def check(self, cmds, cwd, log_path, *args, **kw):
        if self.moved:
            with record.record(self.moved) as current:
                current["state"] = "fail"
            self.moved = None
        return super().check(cmds, cwd, log_path, *args, **kw)

    def refused(self, **files):
        first = self.member("fix-image", 1, once="true", **IMAGE)
        behind = self.member("fix-next", 2, once="true", **files)
        self.moved = first
        land.check_line(self.turn)
        self.assertIsNone(self.moved, "its once commands never ran")
        self.assertNotIn("land", self.wait(first))
        self.assertEqual(self.wait(behind).get("after", {}), {})
        return self.wait(behind)

    def test_a_looks_member_behind_gets_its_own(self):
        self.assertTrue(self.refused(**{"logo.png": "red\n"}).get("looks"))

    def test_code_behind_is_checked_on_the_target(self):
        wait = self.refused(**{"app.js": "x\n"})
        self.assertIn("land", wait)
        self.assertNotIn("looks", wait)


if __name__ == "__main__":
    unittest.main()

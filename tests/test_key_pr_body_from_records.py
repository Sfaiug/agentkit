"""A delivered PR opens with the task and recorded checks; the executor's words come last."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


TITLE = "Keep the retry file"
GOAL = "Keep retry.txt with its expected contents.\n\n### Detail\nPreserve the final newline."
COMMANDS = ("test -f retry.txt", 'test "$(cat retry.txt)" = hello')
SUMMARY = "## Summary\nThe executor says it wrote retry.txt."


class PRBodyFromRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude={**fakeadapter.WORK, "final": SUMMARY}, codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, TITLE, goal=GOAL, done_when=COMMANDS,
                              constraints=("Keep the contents intact.",))
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def body(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        prs = self.gh.prs()
        self.assertEqual(len(prs), 1, prs)
        body = prs[0]["body"]
        self.assertEqual(body, (self.run_dir / "pr-body.md").read_text())
        return body

    def test_goal_opens_with_the_task_title_and_goal_text(self):
        body = self.body()
        self.assertTrue(body.startswith("## Goal\n"), body)
        goal = body.split("## Testing\n", 1)[0]
        self.assertIn(TITLE, goal)
        self.assertIn(GOAL, goal)
        self.assertNotIn("Keep the contents intact.", goal)

    def test_testing_names_both_commands_and_the_commit_they_passed_on(self):
        body = self.body()
        self.assertIn("## Testing\n", body)
        testing = body.split("## Testing\n", 1)[1].split("\n---\n", 1)[0]
        self.assertIn("```bash\n" + "\n".join(COMMANDS) + "\n```", testing)
        reviewed = self.state["round_summaries"][-1]
        self.assertIs(reviewed["done_when"], True)
        self.assertEqual(reviewed["head_sha"], self.state["review"]["head_sha"])
        self.assertIn("passed together", testing.lower())
        self.assertIn(f"round {reviewed['round']}", testing)
        self.assertIn(reviewed["head_sha"], testing)

    def test_executor_words_follow_the_records_under_their_own_heading(self):
        body = self.body()
        self.assertIn("## Executor's summary\n\n" + SUMMARY, body)
        self.assertLess(body.index("## Goal\n"), body.index("## Testing\n"))
        self.assertLess(body.index("## Testing\n"), body.index("- verdict: PASS"))
        self.assertLess(body.index("- run:"), body.index("## Executor's summary\n"))
        self.assertTrue(body.rstrip().endswith(SUMMARY), body)


if __name__ == "__main__":
    unittest.main()

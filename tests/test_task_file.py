"""A task file is read in one module: front matter, title, `after:`, done-when groups and size.

Offline: task files in a temporary directory, read through `agentkit.task` alone.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, task


class TaskFile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="task-file-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, text, name="fix-api.md"):
        path = self.root / name
        path.write_text(text)
        return path

    def body(self, goal="One thing.", cmds=("true",)):
        return (f"# Fix the api\n\n## Goal\n{goal}\n\n## Done when\n```bash\n"
                + "\n".join(cmds) + "\n```\n")

    def test_front_matter_gives_meta_and_title(self):
        path = self.write("---\n# who runs it is the loop's choice\nrepo: none  # scratch\n"
                          "after: base.md\nrounds: 2\nafter: schema.md, Make the docs  # both\n"
                          "---\n" + self.body())
        meta, body, title = task.parse_task(path)
        self.assertEqual(meta, {"repo": "none", "after": "schema.md, Make the docs",
                                "rounds": "2"})
        self.assertTrue(body.startswith("# Fix the api\n"))
        self.assertEqual(title, "Fix the api")

    def test_a_file_without_front_matter_is_all_body(self):
        path = self.write("no heading here\n")
        self.assertEqual(task.parse_task(path), ({}, "no heading here\n", "fix-api"))

    def test_a_missing_closing_fence_is_refused(self):
        path = self.write("---\nrepo: none\n" + self.body())
        for read in (task.parse_task, task.task_files):
            with self.subTest(read.__name__), \
                    self.assertRaisesRegex(config.Error, "closing --- line"):
                read(path)

    def test_a_line_that_is_not_key_value_is_refused(self):
        path = self.write("---\nrepo none\n---\n" + self.body())
        with self.assertRaisesRegex(config.Error, "not `key: value`"):
            task.parse_task(path)

    def test_once_inside_quotes_names_no_marker(self):
        body = self.body(cmds=("cmd-a  # once", 'echo "# once"', "echo '# once'", "cmd-b #once"))
        self.assertEqual(task.done_when_groups(body, Path("task.md")),
                         (['echo "# once"', "echo '# once'"], ["cmd-a", "cmd-b"]))

    def test_a_round_budget_over_the_rule_is_refused(self):
        self.assertIn("over the budget: 3 rounds", task.rounds_refusal(4, "--rounds"))
        self.assertIsNone(task.rounds_refusal(task.TASK_MAX_ROUNDS, "--rounds"))
        self.assertIsNone(task.rounds_refusal("many", "--rounds"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

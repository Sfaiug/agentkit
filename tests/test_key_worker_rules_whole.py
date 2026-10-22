"""Workers get the project's AGENTS.md whole, and `users: real` gives each reviewer one more rule.

A project's AGENTS.md is how its owner instructs every model working on it, and nothing ak hands
a model is cut (owner rules): each prompt of a run, every role and round, carries the body whole
however long, as on the base commit, so the work under review cannot rewrite the rules it is
judged by; the front matter is ak's own to read and is left out.  Its `users:` line is read as
the YAML word it is, quotes and a trailing comment aside: `real` gives a reviewer, and only a
reviewer, the rule that new user-visible behaviour must sit behind the feature switch, and in a
run it is read at the target, so a branch's own change to it never changes its own review.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, a config from akconfig.py, a task from taskfile.py and scripted harnesses
from fakeadapter.py, judged by the prompt files ak writes; this test fails against `/bin/false`.
"""

from itertools import count
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

RULE = "This repository has real users"
REAL = 'users: "real"  # launched in May'
# Past the 8 KB workers' rules were once cut at, multi-byte text in it, under what Codex reads.
BODY = "# Acme rules\n\n" + "".join(f"Rule {n}: the café widget {n} keeps its name.\n"
                                    for n in range(600)) + "LAST RULE: acme-end"
REVIEWERS = ("reviewer", "reviewer-pr", "reviewer-scratch")
EXECUTORS = ("executor", "fixer", "executor-scratch", "fixer-scratch")


def agents_md(front, body=BODY):
    return f"---\n{front}\n---\n{body}\n" if front else f"{body}\n"


class OneTurn(unittest.TestCase):
    """`ak worker`, one headless turn, reads the line in the workspace as written."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])
        fakeadapter.install(cls.home, claude="silent")
        cls.task = cls.home.write("prompt.md", "Review the widget.\n")
        cls.turns = count()

    def prompt(self, front, role):
        """The prompt ak hands one turn of `role` in a workspace whose AGENTS.md has `front`."""
        name = next(self.turns)
        workspace = self.home.path / "code" / f"widgets-{name}"
        workspace.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text(agents_md(front, "# widgets"))
        out = self.home.root / f"out-{name}"
        done = self.home.ak("worker", "opus", str(self.task), "--role", role,
                            "--workspace", str(workspace), "--out", str(out))
        self.assertEqual(done.code, 0, done.out + done.err)
        return (out / "prompt.md").read_text()

    def test_a_reviewer_gets_the_real_users_rule_however_the_word_is_written(self):
        cases = [(REAL, role) for role in REVIEWERS] + [
            (front, "reviewer") for front in ("users: 'real'", "users: real",
                                              "tests: true\nusers: real")]
        for front, role in cases:
            with self.subTest(front=front, role=role):
                self.assertIn(RULE, self.prompt(front, role))

    def test_an_executor_or_fixer_never_gets_it(self):
        for role in EXECUTORS:
            with self.subTest(role):
                self.assertNotIn(RULE, self.prompt(REAL, role))

    def test_none_another_word_or_no_line_gives_no_rule(self):
        for front in ("users: none", "users: realistic", "tests: true", ""):
            with self.subTest(front=front):
                self.assertNotIn(RULE, self.prompt(front, "reviewer"))


class ARun(unittest.TestCase):
    """Every turn of `ak run`: two rounds, the first review failing, so a fixer turn runs too."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])

    def prompts(self, name, front, executor):
        """Each role's prompts, by `round-N/role`, of a two-round run in a fresh project."""
        rig = Rig(self.home, name, files={"AGENTS.md": agents_md(front)})
        # the fixer disputes the finding, as its done waits on every earlier finding's proof
        fakeadapter.install(self.home, claude=[executor, "dispute"], codex="fail")
        task = taskfile.write(self.home, rig.path, f"Add retry file to {name}",
                              front={"rounds": 2})
        done = self.home.ak("run", str(task), "--no-merge", timeout=300)
        runs = [path for path in taskfile.runs(self.home) if path.name.endswith(name)]
        self.assertEqual(len(runs), 1, done.out + done.err)
        run_dir = runs[0]
        found = {str(path.parent.relative_to(run_dir)): path.read_text()
                 for path in run_dir.glob("round-*/*/prompt.md")}
        self.assertEqual(sorted(found), ["round-1/executor", "round-1/reviewer",
                                         "round-2/executor", "round-2/reviewer"])
        self.assertTrue(found["round-2/executor"].startswith("You are the executor, continuing"))
        return found

    def test_every_turn_gets_the_body_whole_without_its_front_matter_and_reviewers_the_rule(self):
        for where, prompt in self.prompts("widgets", REAL, "work").items():
            with self.subTest(where):
                self.assertIn(BODY, prompt)
                self.assertNotIn(REAL, prompt)
                self.assertEqual(RULE in prompt, where.endswith("reviewer"))

    def test_a_branch_rewriting_its_agents_md_changes_neither_its_rules_nor_its_review(self):
        rewrite = {"write": {"retry.txt": "hello\n",
                             "AGENTS.md": agents_md("users: real", "BRANCH RULE: acme-own")},
                   "commit": "add retry.txt", "final": "## Summary\nwrote retry.txt",
                   "hand_in": [["done"]]}
        found = self.prompts("gadgets", "users: none", rewrite)
        for where, prompt in found.items():
            with self.subTest(where):
                self.assertIn(BODY, prompt)
                self.assertNotIn(RULE, prompt)
        # A reviewer reads the diff, which holds the rewrite; the fixer is given the rules.
        self.assertNotIn("BRANCH RULE", found["round-2/executor"])


if __name__ == "__main__":
    unittest.main()

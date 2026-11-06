"""What ak tells a seat of `review_rounds`, `executor_lines` and `orchestrator_lines` is what this host set.

The rulebook a seat opens on, the task template written beside it and `ak run --help` say the
numbers in force, whole sentences reading right at any of them; with no setting they say ak's
defaults.  A `$` the owner wrote in `rules.md` stays as written, as does a task a person left in
the tasks folder.  A config.toml ak cannot use stops a command, never its help.
Black-box: the program `AK_BIN` names, judged by the file it writes for a seat and what it prints.
This test fails against `/bin/false`.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.gitrig import Rig

ECHO = {"one": {"harness": "echo", "model": "echo-1", "provider": "test"},
        "two": {"harness": "echo", "model": "echo-2", "provider": "test"}}
OWN = "Acme's own rule: a seat costs $5, and $rounds, $Rounds and $s mean nothing here.\n"
DRAFT = "# Acme's own draft\n"
DEFAULTS = ("at most 300 added lines with its tests", "you build at most 50 added lines",
            "ak refuses your own PR above 50 lines")


def said(home, *args):
    """What `ak` printed for `args`, having exited 0."""
    done = home.ak(*args)
    assert done.code == 0, done.err
    return done.out


class Help(unittest.TestCase):
    def helps(self, **settings):
        with Home() as home:
            akconfig.write(home, ECHO, settings=settings)
            return said(home, "run", "--help"), said(home, "run", "resume", "--help")

    def test_says_the_rounds_in_force(self):
        for rounds, plural in ((4, "4 rounds"), (1, "1 round")):
            with self.subTest(rounds=rounds):
                run, resume = self.helps(review_rounds=rounds)
                self.assertIn(f"at most {rounds} (default: task rounds or {rounds}).", run)
                self.assertIn(f"a task over {plural} is refused", run)
                self.assertIn(f"raises the round limit, at most {rounds}.", resume)
                self.assertIn(f"--rounds {rounds} --bg", resume)

    def test_says_ak_s_default_with_no_setting(self):
        run, resume = self.helps()
        self.assertIn("at most 3 (default: task rounds or 3).", run)
        self.assertIn("a task over 3 rounds is refused", run)
        self.assertIn("raises the round limit, at most 3.", resume)

    def test_prints_on_a_config_ak_cannot_use(self):
        with Home() as home:
            home.write(".agentkit/config.toml", "review_rounds = -1\n")
            self.assertIn("at most 3 (default", said(home, "run", "--help"))
            self.assertNotEqual(home.ak("run", "task.md").code, 0)

    def test_says_no_limit_without_a_numeric_ceiling(self):
        run, _ = self.helps(executor_lines="no limit", orchestrator_lines="no limit")
        self.assertIn("no limit on added lines", run)
        self.assertIn("you build with no line limit", run)
        self.assertNotIn("at most no limit", run)

    def test_review_off_says_checks_and_no_reviewer(self):
        for text in self.helps(review_rounds=0):
            self.assertIn("No review: a change lands on its checks; no reviewer.", text)
            self.assertNotIn("0 rounds", text)

    def test_executor_off_replaces_task_size_and_says_to_split_own_work(self):
        run, _ = self.helps(executor_lines=0)
        self.assertIn("Executors are off; the orchestrator builds every change itself.", run)
        self.assertIn("at most 50 added lines per PR; split larger changes", run)
        self.assertNotIn("Task size:", run)
        self.assertNotIn("as a task and an executor builds it", run)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Rulebook(unittest.TestCase):
    def book(self, project=None, **settings):
        """The rulebook a seat opened on this host is handed, then its task template."""
        with Home() as home:
            adapters = home.root / "adapters"
            shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
            akconfig.write(home, ECHO, settings=settings)
            home.write(".agentkit/rules.md", OWN)
            task = home.write(".agentkit/tasks/task.md", DRAFT)
            if project:
                rules = "---\ntests: none\nhealth: none\n" + "".join(
                    f"{key}: {value}\n" for key, value in project.items()) + "---\nA project.\n"
                cwd = Rig(home, "acme", files={"AGENTS.md": rules}).path
            else:
                cwd = home.path / "code" / "acme"
                cwd.mkdir(parents=True)
            done = home.ak("orch", "acme", "--model", "one", "--workers", "two", tty=True,
                           cwd=cwd, env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(task.read_text(), DRAFT)
            return ((home.path / ".agentkit/state/rulebook-acme.md").read_text(),
                    (home.path / ".agentkit/state/task-template.md").read_text())

    def test_says_the_numbers_in_force(self):
        book, template = self.book(executor_lines=150, review_rounds=4, orchestrator_lines=20)
        self.assertIn("at most 150 added lines with its tests", template)
        self.assertIn("Four rounds is the budget (`rounds` defaults to 4).", template)
        for words in ("at most 150 added lines with its tests", "you build at most 20 added lines",
                      "ak refuses your own PR above 20 lines"):
            self.assertIn(words, book)
        for words in DEFAULTS:
            self.assertNotIn(words, book)

    def test_reads_right_at_either_end_of_the_budget(self):
        one, many = self.book(review_rounds=1)[1], self.book(review_rounds=7)[1]
        self.assertIn("One round is the budget (`rounds` defaults to 1).", one)
        self.assertIn("7 rounds is the budget (`rounds` defaults to 7).", many)

    def test_reads_right_with_no_line_limits(self):
        book, template = self.book(executor_lines="no limit", orchestrator_lines="no limit")
        for text in (book, template):
            self.assertIn("no limit on added lines", text)
            self.assertNotIn("at most no limit", text)
            self.assertNotIn("split it", text)
        self.assertIn("you build with no line limit", book)

    def test_review_off_reads_right_in_the_rulebook_and_task_template(self):
        book, template = self.book(review_rounds=0)
        self.assertIn("No review: a change lands on its checks; no reviewer.", template)
        for text in (book, template):
            self.assertNotIn("0 rounds", text)

    def test_executor_off_replaces_the_task_instructions(self):
        book, template = self.book(executor_lines=0)
        for text in (book, template):
            self.assertIn("Executors are off; the orchestrator builds every change itself.", text)
            self.assertNotIn("at most 0 added lines", text)
        self.assertIn("at most 50 added lines per PR; split larger changes", book)
        self.assertNotIn("Launch with `ak run <task>.md", book)
        self.assertNotIn("as a task and an executor builds it", book)

    def test_project_executors_off_overrides_the_host_in_the_rulebook(self):
        book, _ = self.book(project={"executor_lines": 0, "orchestrator_lines": 2})
        self.assertIn("Executors are off; the orchestrator builds every change itself.", book)
        self.assertIn("at most 2 added lines per PR; split larger changes", book)
        self.assertNotIn("Launch with `ak run <task>.md", book)
        self.assertNotIn("as a task and an executor builds it", book)

    def test_says_ak_s_defaults_with_no_setting_and_the_owner_s_dollars_as_written(self):
        book, template = self.book()
        self.assertIn("at most 300 added lines with its tests", template)
        self.assertIn("Three rounds is the budget (`rounds` defaults to 3).", template)
        self.assertNotIn("$", template)
        for words in DEFAULTS:
            self.assertIn(words, book)
        self.assertEqual(book.count("$"), OWN.count("$"))
        self.assertTrue(book.endswith(OWN))


if __name__ == "__main__":
    unittest.main()

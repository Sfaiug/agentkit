"""A project declares its suite and live check before a task can launch.

Black-box through AK_BIN: the default tip holds the contract, `none` runs no
command, and a PR can repair an incomplete contract without launching a task.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

NONE = "---\ntests: none\nhealth: none\n---\n# widgets\n"


class ProjectContract(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")

    def project(self, rules):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": rules})
        rig.git("remote", "set-head", "origin", "--auto")
        return rig

    def launch(self, repo, *flags):
        task = taskfile.write(self.home, repo)
        return self.home.ak("run", str(task), *flags, timeout=300)

    def refused(self, done, *keys):
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(taskfile.runs(self.home), [])
        self.assertIn("AGENTS.md", done.err)
        for key in keys:
            self.assertIn(f"{key}:", done.err)
        self.assertIn("command", done.err)
        self.assertIn("none", done.err)

    def test_missing_health_is_refused_before_a_run_exists(self):
        rig = self.project("---\ntests: none\n---\n# widgets\n")
        self.refused(self.launch(rig.path), "health")

    def test_missing_tests_is_refused_even_with_anyway(self):
        rig = self.project("---\nhealth: none\n---\n# widgets\n")
        self.refused(self.launch(rig.path, "--anyway", "--bg"), "tests")

    def test_a_job_refuses_before_allocating_any_of_its_runs(self):
        rig = self.project("---\ntests: none\n---\n")
        tasks = [taskfile.write(self.home, rig.path, name=name) for name in ("api", "web")]
        done = self.home.ak("run", *map(str, tasks), "--bg")
        self.refused(done, "health")

    def test_missing_agents_is_refused(self):
        rig = self.project(NONE)
        rig.git("rm", "AGENTS.md")
        rig.commit({}, "remove rules")
        self.refused(self.launch(rig.path), "tests", "health")

    def test_body_lines_and_empty_values_do_not_declare_commands(self):
        rig = self.project("---\ntests: \nhealth: \n---\ntests: none\nhealth: none\n")
        self.refused(self.launch(rig.path), "tests", "health")

    def test_local_rules_do_not_supply_a_line_missing_on_the_default_tip(self):
        rig = self.project("---\ntests: none\n---\n# widgets\n")
        rig.git("checkout", "-qb", "local")
        rig.commit({"AGENTS.md": NONE}, push=False)
        rig.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.refused(self.launch(rig.path), "health")

    def test_none_merges_without_a_suite_or_a_health_command(self):
        rig = self.project(NONE)
        GitHub(self.home)
        self.home.fake("none", '#!/bin/sh\ntouch "$HOME/none-ran"\nexit 23\n')
        # The checkout cannot replace the target's explicit absence of a suite.
        (rig.path / "AGENTS.md").write_text("---\ntests: false\nhealth: false\n---\n")
        done = self.launch(rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual((state.get("verdict"), state.get("merged")), ("PASS", True))
        self.assertIn("retry.txt", rig.files())
        self.assertFalse((state.get("health") or {}).get("command"))
        self.assertFalse((self.home.path / "none-ran").exists())
        checked = state["final_check"]
        self.assertEqual((checked["outcome"], checked["suite"]), ("passed", None))
        self.assertEqual(rig.origin("log", "-1", "--format=%b", "main"), "* add retry.txt")

    def test_uncached_default_is_resolved_for_tasks_and_jobs(self):
        rig = self.project(NONE)
        for count in (1, 2):
            with self.subTest(tasks=count):
                rig.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
                tasks = [taskfile.write(self.home, rig.path, name=f"task-{count}-{n}")
                         for n in range(count)]
                done = self.home.ak("run", *map(str, tasks), "--no-merge", timeout=300)
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(rig.git("symbolic-ref", "refs/remotes/origin/HEAD"),
                                 "refs/remotes/origin/main")

    def test_uncached_default_applies_the_round_budget_before_launch(self):
        akconfig.write(self.home, ["opus", "astra"], settings={"review_rounds": 5})
        rig = self.project("---\ntests: none\nhealth: none\nreview_rounds: 2\n---\n")
        for flags, front in ((("--rounds", "3"), {}), ((), {"rounds": 3})):
            for count in (1, 2):
                with self.subTest(flags=flags, tasks=count):
                    rig.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
                    tasks = [taskfile.write(self.home, rig.path, name=f"limit-{n}", front=front)
                             for n in range(count)]
                    done = self.home.ak("run", *map(str, tasks), *flags, "--no-merge", "--bg", timeout=30)
                    self.assertEqual(done.code, 2, done.out + done.err)
                    self.assertEqual(taskfile.runs(self.home), [])

    def test_a_review_pr_can_add_the_missing_line(self):
        rig = self.project("---\ntests: none\n---\n# widgets\n")
        gh = GitHub(self.home)
        rig.branch("add-health", {"AGENTS.md": NONE})
        url = gh.open_pr(rig, "add-health", author="other-dev")
        done = self.home.ak("run", "--review-pr", url, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual((state.get("verdict"), state.get("review_posted")), ("PASS", True))

    def test_a_scratch_task_has_no_project_contract(self):
        done = self.launch("none")
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual((state.get("verdict"), state.get("scratch")), ("PASS", True))


if __name__ == "__main__":
    unittest.main()

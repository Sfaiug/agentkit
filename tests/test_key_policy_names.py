"""Policy names, automatic host migration and inclusive orchestrator limits, through AK_BIN."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FAILING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}


class PolicyNames(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        self.task = taskfile.write(self.home, self.rig.path)
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def reviews(self):
        return sum(turn["role"] == "reviewer" for fake in self.fakes.values() for turn in fake.runs())

    def two_rounds(self):
        self.fakes["claude"].behave("work", "dispute")
        self.fakes["codex"].behave(FAILING)
        done = self.home.ak("run", str(self.task), "--no-merge", timeout=300)
        directory = taskfile.only_run(self.home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual((state["state"], state["verdict"], state["rounds"]), ("fail", "FAIL", 2))
        self.assertEqual([row["verdict"] for row in state["round_summaries"]], ["FAIL", "FAIL"])
        self.assertIn("rounds: 2 of 2", (directory / "result.md").read_text().splitlines())

    def test_review_rounds_sets_the_budget(self):
        akconfig.write(self.home, ["opus", "astra"], settings={"review_rounds": 2})
        self.two_rounds()

    def test_any_command_migrates_host_keys_and_keeps_every_value(self):
        akconfig.write(self.home, ["opus", "astra"],
                       settings={"rounds": 2, "review_lines": 120, "seat_lines": 40, "custom_flag": 7})
        expected = akconfig.read(self.home)
        for old, new in (("rounds", "review_rounds"), ("review_lines", "executor_lines"),
                         ("seat_lines", "orchestrator_lines")):
            expected[new] = expected.pop(old)
        done = self.home.ak("run", "--help")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(akconfig.read(self.home), expected)
        self.two_rounds()

    def test_migration_keeps_unrelated_toml_verbatim(self):
        for extra in ("custom_number = nan\n", "[extra]\nitems = [1, {knob = 2}]\n",
                      'note = """\nrounds = 99\nseat_lines = 12\n"""\n'):
            with self.subTest(extra=extra):
                path = self.home.write(".agentkit/config.toml", "'rounds' = 2\nseat_lines = 40\n" + extra)
                done = self.home.ak("run", "--help")
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(path.read_text(), "review_rounds = 2\norchestrator_lines = 40\n" + extra)

    def test_simultaneous_first_commands_all_migrate_safely(self):
        path = self.home.write(".agentkit/config.toml", "rounds = 2\nseat_lines = 40\n")
        hooks = self.home.path / "hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "from pathlib import Path\nimport time\nreplace = Path.replace\n"
            "def paused(self, target):\n"
            "    if self.name == 'config.tmp':\n        time.sleep(0.5)\n"
            "    return replace(self, target)\nPath.replace = paused\n")
        def help_command(_):
            return self.home.ak("run", "--help", env={"PYTHONPATH": str(hooks)}, timeout=15)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(help_command, range(4)))
        for done in results:
            self.assertEqual(done.code, 0, done.err)
        self.assertEqual(path.read_text(), "review_rounds = 2\norchestrator_lines = 40\n")

    def front(self, key, value):
        text = f"---\n{key}: {value}\n---\nA project.\n"
        self.rig.commit({"AGENTS.md": text}, "project policy")
        self.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        return text

    def test_executor_lines_in_project_front_matter_blocks_before_review(self):
        self.front("executor_lines", 120)
        self.fakes["claude"].behave({"write": {"retry.txt": "row\n" * 150},
                                    "commit": "the change", "hand_in": [["done"]]})
        done = self.home.ak("run", str(self.task), "--no-merge", timeout=300)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual((done.code, state["verdict"]), (1, "BLOCKED"), done.out + done.err)
        self.assertIn("a first review takes at most 120; split it", state["error"])
        self.assertEqual(self.reviews(), 0)

    def test_old_project_keys_are_refused_without_rewriting_the_file(self):
        for old, new in (("rounds", "review_rounds"), ("review_lines", "executor_lines"),
                         ("seat_lines", "orchestrator_lines")):
            with self.subTest(key=old):
                text = self.front(old, 2)
                done = self.home.ak("run", str(self.task), timeout=60)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn(new, done.err)
                self.assertEqual((self.rig.path / "AGENTS.md").read_text(), text)
                self.assertEqual(taskfile.runs(self.home), [])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))

    def test_own_pr_limit_includes_fifty_and_refuses_fifty_one(self):
        gh = GitHub(self.home)
        Seat(self.home, "acme", model="opus", cwd=self.rig.path, alive=False, planned=True)
        for lines, code, reviewed in ((50, 0, 1), (51, 2, 0)):
            with self.subTest(lines=lines):
                branch = f"change-{lines}"
                self.rig.branch(branch, {"contrib.txt": "".join(f"row {n}\n" for n in range(lines))})
                before = self.reviews()
                done = self.home.ak("run", "--review-pr", gh.open_pr(self.rig, branch, title=branch),
                                    "--no-merge", cwd=self.rig.path,
                                    env={"AGENTKIT_SESSION": "acme"}, timeout=300)
                self.assertEqual(done.code, code, done.out + done.err)
                self.assertEqual(self.reviews() - before, reviewed)
                if code:
                    self.assertIn("at most 50 added lines", done.err)


if __name__ == "__main__":
    unittest.main()

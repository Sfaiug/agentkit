"""A change's checks pass on HEAD, one fails on base, and HEAD is left clean."""

from contextlib import ExitStack
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from fixtures.hand_in import submitting
from agentkit import config, run, worker
from agentkit import record


# true only on the old code: both replays are commits on base, the branch's files laid over
ON_BASE = "! grep -q 'if items' broken.py"


class RegressionFailsBefore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-regression-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "tests").mkdir()
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0]\n")
        (self.wt / "keep.txt").write_text("base\n")
        (self.wt / "tests/check.py").write_text("assert True\n")
        (self.wt / "tests/removed.py").write_text("assert True\n")
        self.commit("Existing defect")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        self.directory = self.root / "run files"
        (self.directory / "round-1").mkdir(parents=True)
        self.script = self.root / "check.sh"     # a check of the task's own, not a fix run's
        self.logs = []

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def loop(self, cmds=None, state=None, suite=None):
        if state is None:
            workers = self.cfg["defaults"]["workers"]
            executor = workers[0]
            reviewer = next(n for n in workers if config.model(self.cfg, n)["provider"] !=
                            config.model(self.cfg, executor)["provider"])
            state = {"run_id": "regression-test", "state": "running", "base": "main",
                     "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                     "executor": executor, "reviewer": reviewer, "round_summaries": [],
                     "base_proof": "owed"}
            record.save_state(self.directory, state)
        cmds = cmds if cmds is not None else [f"bash {shlex.quote(str(self.script))}"]
        added = [f"{suite}  # once"] if suite else []     # as `with_suite` adds the declared one
        lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                      "# Fix empty input", cmds + added, "context", [])
        lp.rnd = 1
        return lp

    def assert_restored(self, head, untracked=False):
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), head)
        self.assertEqual(run.git(self.wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(self.wt, "status", "--porcelain",
                                 "--untracked-files=" + ("no" if untracked else "normal")), "")

    def test_an_unproven_round_goes_on_and_says_why(self):
        # the owner's rule (7 Oct): ak proves what it can and records why when it cannot
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Change behaviour")
        self.script.write_text("exit 0\n")
        lp = self.loop()
        head = run.git(self.wt, "rev-parse", "HEAD")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn(f"base proof: none shown (every check passes on base {self.base[:12]}", text)
        state = record.read_state(self.directory)
        self.assertEqual(state["base_proof"], "owed")
        self.assertIn("every check passes on base", state["base_proof_note"])
        self.assertIn(run.base_proof_line(state), run.pr_body({**state, "verdict": "PASS"}))
        self.assert_restored(head)

    def test_real_regression_is_red_then_green_and_probed_once_across_resume(self):
        (self.wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "tests/check [1].py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "tests/removed.py").unlink()
        self.script.write_text(
            "set -e\nexport PYTHONPATH=.\n"
            "test ! -e tests/removed.py || exit 0\n"
            "if ! git symbolic-ref -q HEAD >/dev/null; then\n"
            "  echo probe > probe-output\n  echo probe > keep.txt\nfi\n"
            "python3 tests/check.py\npython3 'tests/check [1].py'\necho 'empty input passed'\n")
        before = subprocess.run(["bash", str(self.script)], cwd=self.wt, capture_output=True, text=True)
        self.assertNotEqual(before.returncode, 0)
        self.assertIn("IndexError", before.stderr)
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop()
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        base_output = (self.directory / "base.log").read_text()
        self.assertIn(self.base, base_output)
        self.assertIn("[exit 1]", base_output)
        self.assertIn("IndexError", base_output)
        self.assertIn("[exit 0]", text)
        self.assertIn("empty input passed", text)
        self.assert_restored(head)
        lp.state["step"] = "reviewer"
        self.assertEqual(run.settled_gate(lp), (True, text))
        resumed = self.loop(state=record.read_state(self.directory))
        with patch.object(worker, "boxed", wraps=worker.boxed) as limited:
            self.assertTrue(run.verify_work(resumed)[0])
        self.assertEqual(len(limited.call_args_list), 1, "base was probed again after resume")
        self.assertEqual((self.directory / "base.log").read_text(), base_output)
        self.assert_restored(head)

    def test_base_bytecode_does_not_leak_into_done_when_on_head(self):
        module = self.wt / "same.py"
        module.write_text('value = "base"\n')
        (self.wt / ".gitignore").write_text("__pycache__/\n")
        self.commit("Add same-size fixture")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        size = module.stat().st_size
        module.write_text('value = "head"\n')
        self.assertEqual(module.stat().st_size, size)
        # Equal whole-second mtimes make the base's bytecode look valid on HEAD.
        (self.wt / "tests/check.py").write_text(
            'import os\nos.utime("same.py", (1700000000, 1700000000))\n'
            'import same\nprint("saw", same.value)\nassert same.value == "head", same.value\n')
        self.script.write_text("PYTHONPATH=. python3 tests/check.py\n")
        self.commit("Change the fixture without changing its size")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop()
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": ""}):
            self.assertEqual(run.fails_on_base(lp), "")
            self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")
            base_output = (self.directory / "base.log").read_text()
            self.assertIn("saw base", base_output)
            self.assertIn("[exit 1]", base_output)
            self.assert_restored(head)
            ok, text = run.verify_work(lp)
            self.assertTrue(ok, text)
            self.assertIn("saw head", text)
        self.assertTrue(list((self.wt / "__pycache__").glob("same.*.pyc")))
        self.assert_restored(head)

    def test_checks_that_pass_on_base_fail_the_gate_and_failing_ones_never_probe(self):
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Change behaviour")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop(["true"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn(f"every check passes on base {self.base[:12]}", text)
        (self.directory / "base.log").unlink()
        lp = self.loop(["false"])
        self.assertFalse(run.verify_work(lp)[0])
        self.assertFalse((self.directory / "base.log").exists())
        self.assert_restored(head)

    def test_a_run_that_owes_no_proof_is_not_probed(self):
        # a PR review, or a run launched before the rule: its record owes none
        lp = self.loop(["true"])
        del lp.state["base_proof"]
        self.assertTrue(run.verify_work(lp)[0])
        self.assertFalse((self.directory / "base.log").exists())

    def test_a_check_reading_a_changed_file_reads_it_as_base_has_it(self):
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop(["grep -q 'if items' broken.py"])     # names a changed file, not a test
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("[exit 1]", (self.directory / "base.log").read_text())
        self.assert_restored(head)

    def test_one_failing_check_on_base_is_enough(self):
        (self.wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")
        lp = self.loop(["true", "PYTHONPATH=. python3 tests/check.py", "test -f keep.txt"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def fixed(self):
        (self.wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")

    def test_a_check_s_own_set_e_holds_on_base(self):
        self.fixed()
        lp = self.loop(["set -e; PYTHONPATH=. python3 tests/check.py; echo check-completed"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_a_task_checked_only_at_landing_has_no_check_of_its_own(self):
        self.fixed()
        lp = self.loop(["PYTHONPATH=. python3 tests/check.py  # once"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("the task has no check of its own that runs each round", text)

    def test_a_suite_split_into_shards_is_no_check_of_the_task_s_own(self):
        # the gate runs it in pieces; it is the repository's suite, not this change's check
        self.fixed()
        lp = self.loop(["true", "test -n \"$AK_SHARD\" || PYTHONPATH=. python3 tests/check.py"])
        self.assertEqual(run.own_checks(lp), ["true"])

    def test_the_suite_the_loop_added_is_no_check_of_the_task_s_own(self):
        # it would fail on base; the task's own check does not, whatever the target declares
        self.fixed()
        lp = self.loop(["true"], suite="PYTHONPATH=. python3 tests/check.py")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("every check passes on base", text)

    def test_a_task_with_no_check_of_its_own_proves_nothing(self):
        self.fixed()
        lp = self.loop([], suite="PYTHONPATH=. python3 tests/check.py")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("the task has no check of its own that runs each round", text)

    def test_a_launch_owes_a_base_proof_and_a_pr_review_none(self):
        for opts, owed in (({}, "owed"), ({"--review-pr": "https://github.com/acme/acme/pull/1"}, None)):
            with self.subTest(opts=opts):
                directory = config.RUNS / f"launch-{len(opts)}"
                directory.mkdir(parents=True)
                run.capture_launch(directory, opts, cfg=self.cfg)
                self.assertEqual(record.read_state(directory).get("base_proof"), owed)

    def test_a_compound_check_whose_step_a_signal_ends_on_base_fails_there_as_a_proof_would(self):
        # its shell finishes with 128 + the signal, which a reviewer's proof counts as failing
        self.fixed()
        for signal_ in ("TERM", "KILL"):
            for joined in ("set -e; {step}; echo checked", "{step} && echo checked"):
                with self.subTest(signal=signal_, joined=joined):
                    step = (f"if {ON_BASE}; then sh -c 'kill -{signal_} $$'; fi")
                    lp = self.loop([joined.format(step=step)])
                    lp.state["base_proof"] = "owed"
                    ok, text = run.verify_work(lp)
                    self.assertTrue(ok, text)
                    self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_checks_share_one_base_checkout_as_they_share_head_s(self):
        # the second reads what the first wrote: on base as on HEAD, neither shows the change
        self.fixed()
        lp = self.loop(["printf ready > check-input.tmp",
                        "test -f check-input.tmp && rm check-input.tmp"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("every check passes on base", text)

    def test_a_failing_check_proves_the_change_under_an_inherited_set_e(self):
        self.fixed()
        (self.root / "errexit.sh").write_text("set -e\n")
        for env in ({"SHELLOPTS": "errexit"}, {"BASH_ENV": str(self.root / "errexit.sh")}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                lp = self.loop(["PYTHONPATH=. python3 tests/check.py"])
                lp.state["base_proof"] = "owed"
                ok, text = run.verify_work(lp)
                self.assertTrue(ok, text)
                self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_a_check_that_fails_only_because_it_is_replayed_shows_nothing(self):
        # whatever sets a replay apart from the round's own gate sets both replays apart: a
        # check that needs the run's own checkout is left out, and with none left the round
        # goes on unproven, as before the rule
        self.fixed()
        in_gate = f"test \"$PWD\" = {shlex.quote(str(self.wt))}"
        ok, text = run.verify_work(self.loop([in_gate]))
        self.assertTrue(ok, text)
        self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")
        lp = self.loop([in_gate, "PYTHONPATH=. python3 tests/check.py"])
        lp.state["base_proof"] = "owed"
        ok, text = run.verify_work(lp)    # the other check still proves it
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_a_check_that_reads_the_checkout_rather_than_the_code_shows_nothing(self):
        # both replays are commits on base made alike: what a check reads of the checkout
        # itself -- its cleanliness, what is staged, its commit -- is the same on both
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        (self.wt / "tests/check.py").write_text("assert True, 'checks no changed behaviour'\n")
        self.commit("fix: change behaviour with no check of it")
        head = run.git(self.wt, "rev-parse", "HEAD")
        for check in ("git diff --quiet HEAD",
                      "git diff --quiet HEAD || ! git diff --quiet HEAD -- broken.py",
                      "git log -1 --format=%s | grep -q '^Existing defect$'",
                      "git log -1 --format=%s | grep -q '^fix:'"):
            with self.subTest(check=check):
                lp = self.loop(["python3 tests/check.py", check])
                lp.state["base_proof"] = "owed"
                run.verify_work(lp)
                self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")
                self.assert_restored(head)

    def test_a_proof_needs_no_git_author(self):
        self.fixed()
        run.git(self.wt, "config", "user.useConfigOnly", "true")
        run.git(self.wt, "config", "--unset", "user.name")
        run.git(self.wt, "config", "--unset", "user.email")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop(["PYTHONPATH=. python3 tests/check.py"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")
        proof = run.proof_on(lp, "PYTHONPATH=. python3 tests/check.py",
                             self.directory / "review-proof.log", self.base, head)
        self.assertEqual(proof["returncode"], 1, proof)
        self.assert_restored(head)

    def test_a_check_the_replays_cannot_run_leaves_the_round_unproven_beside_one_that_passes(self):
        # the real test needs the run's own checkout (an installed dependency, say); a lint
        # beside it passes everywhere: the replays cannot tell, which never fails the round
        self.fixed()
        in_gate = f"test \"$PWD\" = {shlex.quote(str(self.wt))}"
        ok, text = run.verify_work(self.loop(["true", in_gate]))
        self.assertTrue(ok, text)
        self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")

    def test_a_test_in_another_language_s_layout_reaches_base(self):
        (self.wt / "spec").mkdir()
        (self.wt / "spec/old_spec.py").write_text("assert True\n")
        self.commit("An old spec")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        (self.wt / "spec/first_spec.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")
        lp = self.loop(['for f in spec/*_spec.py; do PYTHONPATH=. python3 "$f" || exit 1; done'])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_the_second_replay_runs_only_once_a_check_did_not_pass_on_base(self):
        self.fixed()
        ok, text = run.verify_work(self.loop(["true"]))
        self.assertTrue(ok, text)
        self.assertTrue((self.directory / "base.log").exists())
        self.assertFalse((self.directory / "head.log").exists())

    def test_a_branch_changing_more_paths_than_a_command_line_holds_is_replayed(self):
        data = self.wt / "data"
        data.mkdir()
        for index in range(12000):
            (data / f"{'x' * 200}-{index}").write_text("")
        self.fixed()
        ok, text = run.verify_work(self.loop(["PYTHONPATH=. python3 tests/check.py"]))
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_a_test_folder_s_other_files_never_fail_the_round_nor_prove_it(self):
        # a file under tests/ not named as a test may be code its test shows (a gate script,
        # changed or added) or a helper the test needs: either way the round goes on unproven
        (self.wt / "tests/gate.py").write_text("def verdict():\n    return 'old'\n")
        (self.wt / "tests/test_gate.py").write_text("import gate\nassert gate.verdict() == 'old'\n")
        self.commit("A gate and its test")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        branches = {
            "changed code": {"tests/gate.py": "def verdict():\n    return 'new'\n",
                             "tests/test_gate.py": "import gate\nassert gate.verdict() == 'new'\n"},
            "added code": {"tests/pair.py": "def pair():\n    return 2\n",
                           "tests/test_pair.py": "import pair\nassert pair.pair() == 2\n"},
            "added helper": {"tests/helper.py": "def same(x):\n    return x\n",
                             "tests/test_first.py": "import helper\nassert helper.same(1) == 1\n"}}
        for kind, files in branches.items():
            with self.subTest(kind=kind):
                run.git(self.wt, "checkout", "-q", "-B", "ak/fix-api", self.base)
                for name, text in files.items():
                    (self.wt / name).write_text(text)
                (self.wt / "README.md").write_text(f"{kind}\n")
                self.commit(kind)
                test = next(name for name in files if "/test_" in name)
                lp = self.loop([f"PYTHONPATH=tests python3 {test}"])
                lp.state["base_proof"] = "owed"
                ok, text = run.verify_work(lp)
                self.assertTrue(ok, text)
                self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")

    def test_a_branch_changing_nothing_but_tests_owes_no_proof(self):
        (self.wt / "tests/test_more.py").write_text("assert True\n")
        self.commit("One more test")
        ok, text = run.verify_work(self.loop(["python3 tests/test_more.py"]))
        self.assertTrue(ok, text)
        self.assertFalse((self.directory / "base.log").exists())

    def test_a_folder_the_branch_turned_into_a_file_is_replayed(self):
        (self.wt / "settings").mkdir()
        (self.wt / "settings/default.txt").write_text("old\n")
        self.commit("Settings as a folder")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "rm", "-q", "-r", "settings")
        (self.wt / "settings").write_text("new\n")
        self.commit("Settings as a file")
        ok, text = run.verify_work(self.loop(["test -f settings"]))
        self.assertTrue(ok, text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "proven")

    def test_a_replay_never_sees_what_another_replay_s_checks_wrote(self):
        # the round's own gate runs in the run's checkout, each replay in one of its own
        (self.wt / ".gitignore").write_text("ignored-ready.tmp\n")
        self.commit("Ignore generated check data")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        (self.wt / "tests/check.py").write_text("assert True\n# no behaviour assertion\n")
        self.commit("Handle empty input without testing it")
        head = run.git(self.wt, "rev-parse", "HEAD")
        in_gate = f"test \"$PWD\" = {shlex.quote(str(self.wt))}"
        for kind, checks in (
                ("ignored", [f"{in_gate} || test -f ignored-ready.tmp",
                             f"{in_gate} || touch ignored-ready.tmp"]),
                ("untracked", [f'{in_gate} || test "$(cat input.tmp)" = ready',
                               f"if {in_gate}; then printf initial > input.tmp; "
                               "else printf ready > input.tmp; fi"]),
                ("git config", [f'{in_gate} || test "$(git config --get ak.ready)" = yes',
                                f"{in_gate} || git config ak.ready yes"])):
            with self.subTest(kind=kind):
                lp = self.loop(checks)
                ok, _ = run.verify_work(lp)
                self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")
                self.assert_restored(head, untracked=True)
                self.assertEqual(run.git(self.wt, "config", "--get", "ak.ready", check=False), "")
                run.git(self.wt, "clean", "-qfdx")      # what this kind's gate wrote

    def test_a_check_s_background_children_finish_before_the_next_on_base_as_on_head(self):
        # the gate waits for every child of a check before the next: so does the replay
        self.fixed()
        lp = self.loop(["(sleep 1; printf ready > check-input.tmp) &",
                        "test -f check-input.tmp && rm check-input.tmp"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("every check passes on base", text)

    def test_a_failing_check_whose_child_outlives_the_limit_proves_nothing(self):
        self.fixed()
        lp = self.loop(["PYTHONPATH=. python3 tests/check.py || { sleep 60 & exit 1; }"])
        lp.done_when_limit = 5
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("did not finish on base", text)
        self.assertNotEqual(record.read_state(self.directory).get("base_proof"), "proven")

    def test_a_check_that_cannot_start_on_base_proves_nothing(self):
        # the tool it runs is new on the branch and no test, so base has none: the shell's 127
        (self.wt / "probe-tool.sh").write_text("exit 0\n")
        (self.wt / "probe-tool.sh").chmod(0o755)
        self.fixed()
        ok, text = run.verify_work(self.loop(["./probe-tool.sh"]))
        self.assertTrue(ok, text)
        self.assertIn("did not finish on base", text)

    def test_what_a_check_prints_never_decides_another_s_exit(self):
        # it prints the next check's line as the log names it, and a failing mark under it
        (self.wt / "tests/spoof.py").write_text("print('$ true')\nprint('[exit 1]')\n")
        self.commit("A check that prints another's header")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        self.fixed()
        ok, text = run.verify_work(self.loop(["python3 tests/spoof.py", "true"]))
        self.assertTrue(ok, text)
        self.assertIn("every check passes on base", text)

    def test_a_repeated_check_line_runs_each_time_on_base_as_on_head(self):
        self.fixed()
        lp = self.loop(["rm -f twice.tmp", "printf x >> twice.tmp", "printf x >> twice.tmp",
                        'test "$(cat twice.tmp)" = xx'])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("every check passes on base", text)

    def test_interrupted_probe_leaves_the_branch_without_recording_success(self):
        self.fixed()
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop(["PYTHONPATH=. python3 tests/check.py"])
        limited = worker.boxed

        def interrupt(cmd, *args, **kwargs):
            checkout = Path(kwargs["cwd"])
            if "if items" not in (checkout / "broken.py").read_text():    # the probe, on base
                (checkout / "broken.py").write_text("probe\n")
                (checkout / "probe-output").write_text("probe\n")
                raise run.Stopped("fixture stop")
            return limited(cmd, *args, **kwargs)

        with patch.object(worker, "boxed", side_effect=interrupt):
            with self.assertRaises(run.Stopped):
                run.verify_work(lp)
        self.assert_restored(head)
        self.assertEqual(record.read_state(self.directory).get("base_proof"), "owed")

    def test_a_check_a_signal_ends_on_base_is_unfinished_not_failing(self):
        self.fixed()
        # passes on HEAD; on base a signal ends it before it says anything
        lp = self.loop([f"{ON_BASE} && kill -TERM $$; true"])
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertIn("did not finish on base", text)
        self.assertEqual(record.read_state(self.directory)["base_proof"], "owed")

if __name__ == "__main__":
    unittest.main(verbosity=2)

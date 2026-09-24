"""agentkit v5aa: main moving under a fix never fails the run. Entirely offline.

Real throwaway git repos under a temp dir with a bare `origin`; no network, no real
harness.  The fixer is a stub that edits files and runs `git rebase --continue` itself.
"""

from contextlib import ExitStack
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


def make_repos(root):
    """A bare origin, an owner clone that moves it, and a work clone on ak/test."""
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    for cwd in (owner,):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")
    (owner / "base.txt").write_text("base\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "base")
    run.git(owner, "push", "origin", "main")
    wt = root / "wt"
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", "ak/test")
    (wt / "work.txt").write_text("work\n")
    run.git(wt, "add", ".")
    run.git(wt, "commit", "-m", "work")
    return remote, owner, wt


def make_loop(root, wt, rounds=3):
    run_dir = root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "log.txt").touch()
    head = run.git(wt, "rev-parse", "HEAD")
    tree = run.git(wt, "rev-parse", "HEAD^{tree}")
    base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
    lines = []

    def log(msg):
        line = f"[00:00:00] {msg}"
        lines.append(line)
        print(line, flush=True)
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(line + "\n")

    state = {
        "run_id": "v5aa-test", "title": "v5aa", "state": "running", "verdict": "PASS",
        "review": {"executor": "opus", "executor_provider": "p1", "reviewer": "astra",
                   "reviewer_provider": "p2", "returncode": 0, "verdict": "PASS",
                   "done_when": True, "head_sha": head, "tree_sha": tree},
        "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                             "summary": "work", "head_sha": head, "tree_sha": tree}],
        "rounds": rounds, "base": "origin/main", "target": "origin/main",
        "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
        "repo": str(wt), "executor": "opus", "reviewer": "astra",
        "merge_method": "squash", "merged": False, "merge_failed": False,
        "merge_note": None,
    }
    run.save_state(run_dir, state)
    lp = run.Loop({}, run_dir, state, {}, log, wt, "body", ["true"], "context", [])
    return lp, run_dir, lines


def move_owner(owner, name, value="x\n"):
    (owner / name).write_text(value)
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", f"move {name}")
    run.git(owner, "push", "origin", "main")


# One fake harness for every model in the catalogue: offline answers only, recording
# nothing but the verdict.  The executor branch must never run in these tests.
ADAPTER = '''import json, pathlib, sys
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
if role == "reviewer":
    (out / "final.md").write_text("VERDICT: PASS\\n\\n## Findings\\n- none\\n")
else:
    (out / "final.md").write_text("## Summary\\nShould never run.")
(out / "session_id").write_text("session-" + role)
'''





class V5aa(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5aa-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))

    def script(self, path, text):
        path.write_text(f"#!{sys.executable}\n{text}")
        path.chmod(0o755)

    def log_text(self, run_dir):
        return (run_dir / "log.txt").read_text()

    def test_v5aa_pinned_tip_retries_when_main_moves_mid_lap(self):
        _, owner, wt = make_repos(self.root)
        tip0 = run.git(wt, "rev-parse", "origin/main^{commit}")
        lp, run_dir, lines = make_loop(self.root, wt)
        real_out = run.git_out
        moved = []

        real_set_base = run.set_base
        saved = []

        def record_set_base(lp2, rev):
            out = real_set_base(lp2, rev)
            saved.append(lp2.state["base_sha"])
            return out

        def hooked(wt2, *args, **kwargs):
            code, out = real_out(wt2, *args, **kwargs)
            if args[:1] == ("rebase",) and not moved:
                # another lane pulls origin forward in the shared .git after the rebase
                # landed and before the checks that follow it: the name has moved, the
                # pinned tip has not.
                move_owner(owner, "moved.txt", "origin moved\n")
                real_out(wt, "fetch", "origin")
                moved.append(True)
            return code, out

        with patch.object(run, "git_out", side_effect=hooked), \
                patch.object(run, "current_review", return_value=True), \
                patch.object(run, "set_base", side_effect=record_set_base):
            self.assertTrue(run.integrate(lp, "origin/main"))
        text = self.log_text(run_dir)
        tip1 = run.git(wt, "rev-parse", "origin/main^{commit}")
        self.assertNotEqual(tip0, tip1)
        self.assertIn("moved to", text)
        self.assertIn(f"rebasing ak/test onto origin/main ({tip0[:12]})", text)
        self.assertIn(f"rebasing ak/test onto origin/main ({tip1[:12]})", text)
        self.assertTrue(run.integrated(wt, tip0))
        self.assertTrue(run.integrated(wt, tip1))
        # every lap saved the pinned commit it rebased onto, never the moving name
        self.assertEqual(saved, [tip0, tip1])
        self.assertEqual(run.read_state(run_dir)["base_sha"], tip1)

    def test_v5aa_conflict_fixer_finished_means_second_rebase_not_abort_words(self):
        _, owner, wt = make_repos(self.root)
        (wt / "shared").write_text("branch intent\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch shared")
        (owner / "shared").write_text("base\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "base shared")
        run.git(owner, "push", "origin", "main")
        (owner / "shared").write_text("target intent\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "target shared")
        run.git(owner, "push", "origin", "main")
        tip1 = run.git(owner, "rev-parse", "main^{commit}")
        lp, run_dir, _ = make_loop(self.root, wt)
        real_set_base = run.set_base
        saved = []

        def record_set_base(lp2, rev):
            out = real_set_base(lp2, rev)
            saved.append(lp2.state["base_sha"])
            return out

        def fixer(lp2, role, text, name):
            (wt / "shared").write_text("both intents\n")
            run.git(wt, "add", "shared")
            run.git(wt, "-c", "core.editor=true", "rebase", "--continue")
            # another lane pulls origin forward in the shared .git after the fixer's
            # rebase finished: HEAD carries the pinned tip, never the moving name.
            move_owner(owner, "second.txt", "second move\n")
            run.git_out(wt, "fetch", "origin")
            return "## Summary\nResolved both sides."

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "verify_work", return_value=(True, "ok")), \
                patch.object(run, "review", return_value="PASS"), \
                patch.object(run, "current_review", return_value=True), \
                patch.object(run, "set_base", side_effect=record_set_base):
            self.assertTrue(run.integrate(lp, "origin/main"))
        text = self.log_text(run_dir)
        self.assertNotIn("did not finish", text)
        self.assertIn("moved to", text)
        self.assertEqual(text.count("rebasing ak/test onto origin/main"), 2)
        tip2 = run.git(wt, "rev-parse", "origin/main^{commit}")
        self.assertNotEqual(tip1, tip2)
        self.assertIn(f"rebasing ak/test onto origin/main ({tip1[:12]})", text)
        self.assertIn(f"rebasing ak/test onto origin/main ({tip2[:12]})", text)
        self.assertTrue(run.integrated(wt, tip2))
        self.assertEqual(saved, [tip1, tip2])
        self.assertEqual(run.read_state(run_dir)["base_sha"], tip2)

    def test_v5aa_unfinished_fixer_aborts_and_records_none(self):
        _, owner, wt = make_repos(self.root)
        (wt / "shared").write_text("branch intent\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch shared")
        (owner / "shared").write_text("target intent\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "target shared")
        run.git(owner, "push", "origin", "main")
        lp, run_dir, _ = make_loop(self.root, wt)
        calls = []

        def fixer(lp2, role, text, name):
            calls.append(name)
            return "## Summary\nDid nothing."

        with patch.object(run, "execute", side_effect=fixer):
            self.assertFalse(run.integrate(lp, "origin/main"))
        text = self.log_text(run_dir)
        self.assertIn("did not finish", text)
        # three conflict rounds work the stopped rebase; none of them is a task round
        self.assertEqual(calls, ["rebase-fixer"] * 3)
        state = run.read_state(run_dir)
        # a conflict is the world moving, never a verdict on the work: the run parks
        # `waiting` with the reason rather than ending FAIL, and records no round for it
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertFalse(state["merge_failed"])
        self.assertIn("did not finish", state["merge_note"])
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1])
        self.assertFalse(run.in_progress(wt, "rebase"))

    def test_v5aa_four_moves_end_with_three_times_note_and_stay_resumable(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        move_owner(owner, "pre.txt", "pre\n")
        t1 = run.git(owner, "rev-parse", "main^{commit}")
        real_out = run.git_out
        real_set_base = run.set_base
        saved, tips, laps = [], [t1], []

        def record_set_base(lp2, rev):
            out = real_set_base(lp2, rev)
            saved.append(lp2.state["base_sha"])
            return out

        def hooked(wt2, *args, **kwargs):
            code, out = real_out(wt2, *args, **kwargs)
            if args[:1] == ("rebase",):
                # every landed lap finds the shared reference advanced again
                laps.append(True)
                move_owner(owner, f"hook{len(laps)}.txt", f"{len(laps)}\n")
                tips.append(run.git(owner, "rev-parse", "main^{commit}"))
                real_out(wt, "fetch", "origin")
            return code, out

        with patch.object(run, "git_out", side_effect=hooked), \
                patch.object(run, "current_review", return_value=True), \
                patch.object(run, "set_base", side_effect=record_set_base):
            self.assertFalse(run.integrate(lp, "origin/main"))
        state = run.read_state(run_dir)
        text = self.log_text(run_dir)
        self.assertIn("moved three times", text)
        self.assertIn("moved three times", state["merge_note"])
        self.assertFalse(state["merge_failed"])
        self.assertEqual(state["state"], "waiting")    # parked like a conflict, never FAIL
        # three laps, never a fourth: the limit is checked before another rebase runs,
        # and every lap saved the pinned commit it rebased onto
        self.assertEqual(text.count("rebasing ak/test onto origin/main"), 3)
        self.assertEqual(saved, tips[:3])
        state["state"] = "fail"
        run.save_state(run_dir, state)
        self.assertTrue(run.failed_in_integration(run.read_state(run_dir), run_dir))
        self.assertEqual(run.continue_line(run.read_state(run_dir), run_dir),
                         "continue: ak run resume v5aa-test")

    def test_v5aa_integration_fail_below_budget_resumes_at_integration(self):
        # the reported race as the old code recorded it: the fixer finished the rebase,
        # so HEAD changed and no recorded review covers it, and the synthetic round 2
        # (FAIL, no done-when, no commit) judged nothing.  Resume must verify this HEAD
        # in place and merge it -- never spend a fixer round on it.
        from unittest.mock import patch as mock_patch
        from agentkit import usage
        tmp_home = self.root / "home"
        with ExitStack() as stack:
            for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
                stack.enter_context(mock_patch.object(config, name, tmp_home / name.lower()))
            stack.enter_context(patch.dict(os.environ, {
                "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
                "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
                "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                config.ADAPTER_DIR_ENV: str(self.root / "adapters")}))
            stack.enter_context(mock_patch.object(usage, "collect", return_value={}))
            stack.enter_context(mock_patch.object(usage, "pick_order",
                                                  return_value=["opus", "astra"]))
            config.ensure_dirs()
            adapters = self.root / "adapters"
            adapters.mkdir()
            for harness in {m["harness"] for m in config.load()["models"].values()}:
                self.script(adapters / f"{harness}.sh", ADAPTER)
            _, owner, wt = make_repos(self.root)
            base = run.git(wt, "rev-parse", "HEAD")
            base_tree = run.git(wt, "rev-parse", "HEAD^{tree}")
            # the commit the fixer rebased onto before the race was recorded
            move_owner(owner, "first.txt", "first\n")
            tip0 = run.git(owner, "rev-parse", "main^{commit}")
            # the fixer's finished rebase onto tip0, exactly as the race left it
            run.git(wt, "fetch", "origin")
            run.git(wt, "rebase", "origin/main")
            head = run.git(wt, "rev-parse", "HEAD")
            tree = run.git(wt, "rev-parse", "HEAD^{tree}")
            self.assertNotEqual(head, base)
            # meanwhile another lane merged, moving origin onward
            move_owner(owner, "later.txt", "later\n")
            run_dir = config.RUNS / "20260916-0000-v5aa-resume"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text(
                "---\nrepo: none\nrounds: 4\n---\n# Resume fixture\n\n## Done when\n```bash\ntrue\n```\n")
            state = {
                "run_id": run_dir.name, "title": "resume fixture", "state": "fail",
                "verdict": "FAIL", "review": None,
                "round_summaries": [
                    {"round": 1, "verdict": "PASS", "done_when": True,
                     "summary": "work", "head_sha": base, "tree_sha": base_tree},
                    {"round": 2, "verdict": "FAIL", "done_when": False,
                     "summary": "fixer work"}],
                "rounds": 4, "base": "origin/main", "target": "origin/main",
                "base_sha": tip0, "branch": "ak/test", "worktree": str(wt),
                "repo": str(wt), "executor": "opus", "reviewer": "astra",
                "merge_method": "squash", "merged": False, "merge_failed": True,
                "merge_note": "the fixer did not finish the rebase of origin/main; "
                              "it was aborted",
            }
            run.save_state(run_dir, state)
            (run_dir / "log.txt").write_text(
                "[00:00:00] ERROR not merged: the fixer did not finish the rebase "
                "of origin/main; it was aborted\n")
            self.assertTrue(run.failed_in_integration(run.read_state(run_dir), run_dir))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.cmd_status([run_dir.name]), 0)
            printed = out.getvalue()
            line = next(l for l in printed.splitlines() if "continue:" in l)
            self.assertEqual(line.strip(), f"continue: ak run resume {run_dir.name}")
            URL = "https://github.com/fixture/repo/pull/1"

            def fake_gh(cwd, *args, **kwargs):
                if args[:2] == ("repo", "view"):
                    return 0, json.dumps({"nameWithOwner": "fixture/repo",
                                          "viewerPermission": "WRITE"})
                if args[:2] == ("pr", "create"):
                    return 0, URL
                if args[:2] == ("pr", "merge"):
                    return 0, "merged"
                if args[:2] == ("api", "graphql"):
                    return 0, json.dumps({"data": {"repository": {"ref": {
                        "branchProtectionRule": None}}}})
                if args[:2] == ("api", "--paginate"):
                    return 0, "[]"
                raise AssertionError(f"unexpected gh: {args[:4]}")

            calls = []

            def no_execute(lp2, role, text, name):
                calls.append(role)
                raise AssertionError("resume must not spend an executor round")

            with mock_patch.object(run, "gh", side_effect=fake_gh), \
                    mock_patch.object(run, "execute", side_effect=no_execute):
                self.assertEqual(run.cmd_resume([run_dir.name]), 0)
            self.assertEqual(calls, [])
            after = run.read_state(run_dir)
            self.assertEqual((after["state"], after["verdict"]), ("pass", "PASS"))
            self.assertTrue(after["merged"])
            # v5ac: the race HEAD is verified in round 3; the lap onto the moved tip
            # keeps that review (identical patch), so no round 4 is added.
            self.assertEqual([e["round"] for e in after["round_summaries"]], [1, 2, 3])
            self.assertTrue(all(e["verdict"] == "PASS" for e in after["round_summaries"]
                                if e["round"] >= 3))
            self.assertEqual(after["review"]["head_sha"], run.git(wt, "rev-parse", "HEAD"))
            self.assertEqual(after["review"]["rebased_from"], head)
            self.assertTrue(after["review"]["patch_id"])
            self.assertIn("review kept", (run_dir / "log.txt").read_text())
            tip = run.git(wt, "rev-parse", "origin/main^{commit}")
            self.assertTrue(run.integrated(wt, tip))
            resumed_log = (run_dir / "log.txt").read_text()
            self.assertNotIn("rebase-fixer", resumed_log)
            self.assertNotIn(": executor", resumed_log)

    def test_v5aa_at_budget_integration_fail_resumes_straight_to_merge(self):
        # the moved note at 2/2 with its PASS review intact: the advertised
        # `--rounds 3` continuation must reuse that review and merge, not start
        # a generic fixer round 3.
        from unittest.mock import patch as mock_patch
        from agentkit import usage
        tmp_home = self.root / "home-budget"
        with ExitStack() as stack:
            for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
                stack.enter_context(mock_patch.object(config, name, tmp_home / name.lower()))
            stack.enter_context(patch.dict(os.environ, {
                "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
                "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
                "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                config.ADAPTER_DIR_ENV: str(self.root / "adapters5")}))
            stack.enter_context(mock_patch.object(usage, "collect", return_value={}))
            stack.enter_context(mock_patch.object(usage, "pick_order",
                                                  return_value=["opus", "astra"]))
            config.ensure_dirs()
            adapters = self.root / "adapters5"
            adapters.mkdir()
            for harness in {m["harness"] for m in config.load()["models"].values()}:
                self.script(adapters / f"{harness}.sh", ADAPTER)
            _, owner, wt = make_repos(self.root)
            head = run.git(wt, "rev-parse", "HEAD")
            tree = run.git(wt, "rev-parse", "HEAD^{tree}")
            base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
            run_dir = config.RUNS / "20260916-0000-v5aa-budget"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text(
                "---\nrepo: none\nrounds: 2\n---\n# Budget fixture\n\n## Done when\n```bash\ntrue\n```\n")
            review = {"executor": "opus", "executor_provider": "anthropic",
                      "reviewer": "astra", "reviewer_provider": "openai",
                      "returncode": 0, "verdict": "PASS", "done_when": True,
                      "head_sha": head, "tree_sha": tree}
            state = {
                "run_id": run_dir.name, "title": "budget fixture", "state": "fail",
                "verdict": "FAIL", "review": dict(review),
                "round_summaries": [
                    {"round": n, "verdict": "PASS", "done_when": True,
                     "summary": "work", "head_sha": head, "tree_sha": tree}
                    for n in (1, 2)],
                "rounds": 2, "base": "origin/main", "target": "origin/main",
                "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
                "repo": str(wt), "executor": "opus", "reviewer": "astra",
                "merge_method": "squash", "merged": False, "merge_failed": False,
                "merge_note": "origin/main moved three times during integration; "
                              "resume to try again",
            }
            run.save_state(run_dir, state)
            (run_dir / "log.txt").write_text(
                "[00:00:00] WARN not merged: origin/main moved three times during "
                "integration; resume to try again\n")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.cmd_status([run_dir.name]), 0)
            self.assertIn(f"continue: ak run resume {run_dir.name} --rounds 3",
                          out.getvalue())
            URL = "https://github.com/fixture/repo/pull/1"

            def fake_gh(cwd, *args, **kwargs):
                if args[:2] == ("repo", "view"):
                    return 0, json.dumps({"nameWithOwner": "fixture/repo",
                                          "viewerPermission": "WRITE"})
                if args[:2] == ("pr", "create"):
                    return 0, URL
                if args[:2] == ("pr", "merge"):
                    return 0, "merged"
                if args[:2] == ("api", "graphql"):
                    return 0, json.dumps({"data": {"repository": {"ref": {
                        "branchProtectionRule": None}}}})
                if args[:2] == ("api", "--paginate"):
                    return 0, "[]"
                raise AssertionError(f"unexpected gh: {args[:4]}")

            calls = []

            def no_execute(lp2, role, text, name):
                calls.append(role)
                raise AssertionError("resume must not spend an executor round")

            with mock_patch.object(run, "gh", side_effect=fake_gh), \
                    mock_patch.object(run, "execute", side_effect=no_execute):
                self.assertEqual(run.cmd_resume([run_dir.name, "--rounds", "3"]), 0)
            self.assertEqual(calls, [])
            after = run.read_state(run_dir)
            self.assertEqual((after["state"], after["verdict"], after["rounds"]),
                             ("pass", "PASS", 3))
            self.assertTrue(after["merged"])
            self.assertIn("going straight to the merge", (run_dir / "log.txt").read_text())

    def test_v5aa_failed_rereview_is_not_an_integration_resume(self):
        from unittest.mock import patch as mock_patch
        tmp_home = self.root / "home-fail"
        with ExitStack() as stack:
            for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
                stack.enter_context(mock_patch.object(config, name, tmp_home / name.lower()))
            stack.enter_context(patch.dict(os.environ, {
                "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
                "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
                "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "PYTHONDONTWRITEBYTECODE": "1"}))
            config.ensure_dirs()
            _, owner, wt = make_repos(self.root)
            run_dir = config.RUNS / "20260916-0000-v5aa-rereview"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text(
                "---\nrepo: none\nrounds: 3\n---\n# Rereview fixture\n\n## Done when\n```bash\ntrue\n```\n")
            head = run.git(wt, "rev-parse", "HEAD")
            tree = run.git(wt, "rev-parse", "HEAD^{tree}")
            base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
            state = {
                "run_id": run_dir.name, "title": "rereview fixture", "state": "fail",
                "verdict": "FAIL", "review": None,
                "round_summaries": [
                    {"round": 1, "verdict": "PASS", "done_when": True,
                     "summary": "work", "head_sha": head, "tree_sha": tree},
                    {"round": 2, "verdict": "FAIL", "done_when": False,
                     "summary": "re-review failed", "head_sha": head, "tree_sha": tree}],
                "rounds": 3, "base": "origin/main", "target": "origin/main",
                "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
                "repo": str(wt), "executor": "opus", "reviewer": "astra",
                "merge_method": "squash", "merged": False, "merge_failed": False,
                "merge_note": "done-when or review after the rebase of origin/main "
                              "did not pass",
            }
            run.save_state(run_dir, state)
            (run_dir / "log.txt").write_text(
                "[00:00:00] WARN not merged: done-when or review after the rebase "
                "of origin/main did not pass\n")
            # the reviewer judged the tree: a fixer round on its findings, not an
            # integration resume with no executor turn (v5aj)
            self.assertFalse(run.failed_in_integration(run.read_state(run_dir), run_dir))
            self.assertTrue(run.judged_in_integration(run.read_state(run_dir), run_dir))
            self.assertEqual(run.continue_line(run.read_state(run_dir), run_dir),
                             f"continue: ak run resume {run_dir.name}")

    def test_v5aa_base_sha_is_the_pinned_commit_not_the_moving_name(self):
        _, owner, wt = make_repos(self.root)
        tip0 = run.git(wt, "rev-parse", "origin/main^{commit}")
        lp, run_dir, _ = make_loop(self.root, wt)
        real_out = run.git_out
        moved = []

        real_set_base = run.set_base
        saved = []

        def record_set_base(lp2, rev):
            out = real_set_base(lp2, rev)
            saved.append(lp2.state["base_sha"])
            return out

        def hooked(wt2, *args, **kwargs):
            code, out = real_out(wt2, *args, **kwargs)
            if args[:1] == ("rebase",) and not moved:
                # the tracking reference moves under the lap; the saved base must
                # still be the commit the retry rebased onto, never the moving name
                move_owner(owner, "moved.txt", "origin moved\n")
                real_out(wt, "fetch", "origin")
                moved.append(True)
            return code, out

        with patch.object(run, "git_out", side_effect=hooked), \
                patch.object(run, "current_review", return_value=True), \
                patch.object(run, "set_base", side_effect=record_set_base):
            self.assertTrue(run.integrate(lp, "origin/main"))
        state = run.read_state(run_dir)
        tip1 = run.git(wt, "rev-parse", "origin/main^{commit}")
        self.assertNotEqual(tip0, tip1)
        self.assertEqual(saved, [tip0, tip1])
        self.assertEqual(state["base_sha"], tip1)
        self.assertRegex(state["base_sha"], r"^[0-9a-f]{40}$")
        self.assertTrue(run.integrated(wt, tip1))


if __name__ == "__main__":
    unittest.main(verbosity=2)

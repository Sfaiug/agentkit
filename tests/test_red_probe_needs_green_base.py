"""Legacy probes need a green old base; a lander checks the bare target's own suite once.

Real commands and temporary git repos; the fixer and repair launcher are fakes.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_red_target as red
from agentkit import config, gate, land, run, watch
from agentkit import record


class GreenBase(unittest.TestCase):
    fixer = red.RedTarget.fixer
    review_call = red.RedTarget.review_call
    assert_on_branch_head_and_clean = red.RedTarget.assert_on_branch_head_and_clean

    def setUp(self):
        red.RedTarget.setUp(self)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        self.repair = self.stack.enter_context(patch.object(run, "start_followups", return_value=None))

    def move_target(self, owner, wt):
        (owner / "breakage").write_text("target moved\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "target breakage")
        run.git(owner, "push", "origin", "main")
        run.git(wt, "fetch", "origin")
        return run.git(owner, "rev-parse", "HEAD")

    def integrate(self, lp, tip):
        # Integration invalidates the review and advances base_sha before probing.
        run.pending_review(lp, "Re-review after integration.")
        run.git(lp.wt, "rebase", tip)
        run.set_base(lp, tip)
        return run.git(lp.wt, "rev-parse", "HEAD")

    def branch_unittest(self, root, every="true"):
        _, owner, wt = red.make_repos(root)
        (wt / "tests").mkdir()
        (wt / "tests/__init__.py").touch()
        (wt / "tests/test_new.py").write_text(
            "from pathlib import Path\nimport unittest\n\n"
            "class New(unittest.TestCase):\n"
            "    def test_no_breakage(self):\n"
            "        self.assertFalse(Path('breakage').exists())\n"
            "    def test_no_poison(self):\n"
            "        self.assertFalse(Path('poison').exists())\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch unittest module")
        cmd = "python3 -m unittest tests.test_new"
        lp, run_dir, lines = red.make_loop(root, wt, [every, f"{cmd}  # once"])
        base = run.git(wt, "merge-base", "HEAD", "origin/main")
        self.assertTrue(gate.run_done_when([cmd], wt, run_dir / "before.log", set())[0])
        lp.state["landing"] = True
        return lp, owner, base, lines, cmd

    def test_a_branch_only_unittest_module_runs_the_fixer_instead_of_parking(self):
        lp, owner, base, lines, cmd = self.branch_unittest(self.root)
        wt, run_dir = lp.wt, lp.run_dir
        tip = self.move_target(owner, wt)
        self.integrate(lp, tip)

        self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer"])
        self.assertNotEqual(record.read_state(run_dir)["state"], "waiting")
        self.repair.assert_not_called()
        self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
        probes = (run_dir / "target-probe.log").read_text()
        self.assertEqual(probes.count(f"$ {cmd} (on "), 2)
        self.assertIn(tip, probes)
        self.assertIn(base, probes)
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_conflict_reviews_keep_the_old_base_for_the_final_check(self):
        for how in ("rebase", "merge"):
            with self.subTest(how=how):
                root = self.root / how
                root.mkdir()
                lp, owner, base, lines, cmd = self.branch_unittest(root)
                wt = lp.wt
                lp.state["merge_method"] = "merge" if how == "merge" else "squash"
                (owner / "work.txt").write_text("target intent\n")
                self.move_target(owner, wt)
                self.turns.clear()

                def fix(lp, role, text, name, **_kw):
                    if not run.in_progress(wt, how):
                        return self.fixer(lp, role, text, name)
                    self.turns.append(name)
                    lp.round_dir.mkdir(parents=True, exist_ok=True)
                    (wt / "work.txt").write_text("both intents\n")
                    run.git(wt, "add", "work.txt")
                    if how == "rebase":
                        run.git(wt, "-c", "core.editor=true", "rebase", "--continue")
                    else:
                        run.git(wt, "commit", "-m", "resolve conflict")
                    return "## Summary\nResolved the conflict."

                with patch.object(run, "execute", side_effect=fix):
                    self.assertTrue(run.integrate(lp, "origin/main"))
                    self.assertTrue(run.final_check(lp, "origin/main"))
                self.assertEqual(self.turns, [f"{how}-fixer", "final-fixer"])
                self.repair.assert_not_called()
                self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
                self.assertNotEqual(record.read_state(lp.run_dir)["state"], "waiting")
                self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_second_final_check_lap_keeps_the_same_old_base(self):
        lp, owner, base, lines, cmd = self.branch_unittest(self.root)
        wt = lp.wt
        (owner / "poison").touch()
        tip = self.move_target(owner, wt)
        self.integrate(lp, tip)

        def fix(lp, role, text, name, **_kw):
            self.turns.append(name)
            lp.round_dir.mkdir(parents=True, exist_ok=True)
            path = "breakage" if len(self.turns) == 1 else "poison"
            (wt / path).unlink()
            run.git(wt, "add", "-A")
            run.git(wt, "commit", "-m", f"fix {path}")
            return f"## Summary\nFixed {path}."

        with patch.object(run, "execute", side_effect=fix):
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer", "final-fixer"])
        self.repair.assert_not_called()
        self.assertEqual("\n".join(lines).count(
            f"fails on {base[:12]} too: needs this branch"), 2)
        probes = (lp.run_dir / "target-probe.log").read_text()
        self.assertEqual(probes.count(f"$ {cmd} (on old base {base})"), 2)
        self.assertNotEqual(record.read_state(lp.run_dir)["state"], "waiting")
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_failed_rebase_gate_keeps_the_old_base_after_its_fixer_review(self):
        lp, owner, base, lines, _ = self.branch_unittest(
            self.root, every="python3 -m unittest tests.test_new.New.test_no_breakage")
        # A landing PASS can keep its checked head without a task-round row.
        lp.state["round_summaries"].clear()
        wt = lp.wt
        (owner / "poison").touch()
        self.move_target(owner, wt)

        def fix(lp, role, text, name, **_kw):
            self.turns.append(name)
            lp.round_dir.mkdir(parents=True, exist_ok=True)
            path = "breakage" if name == "rerun-fixer" else "poison"
            (wt / path).unlink()
            run.git(wt, "add", "-A")
            run.git(wt, "commit", "-m", f"fix {path}")
            return f"## Summary\nFixed {path}."

        with patch.object(run, "execute", side_effect=fix):
            self.assertTrue(run.integrate(lp, "origin/main"))
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["rerun-fixer", "final-fixer"])
        self.repair.assert_not_called()
        self.assertEqual("\n".join(lines).count(
            f"fails on {base[:12]} too: needs this branch"), 2)
        self.assertNotEqual(record.read_state(lp.run_dir)["state"], "waiting")
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_resumed_landing_review_keeps_the_old_base_for_the_final_check(self):
        lp, owner, base, lines, _ = self.branch_unittest(self.root)
        wt, run_dir = lp.wt, lp.run_dir
        tip = self.move_target(owner, wt)
        self.integrate(lp, tip)
        lp = run.Loop(lp.cfg, run_dir, record.read_state(run_dir), {}, lp.log, wt,
                      "body", lp.cmds, "context", [])
        self.assertEqual(run.resume_review(lp), "PASS")
        self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer"])
        self.repair.assert_not_called()
        self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
        self.assertNotEqual(record.read_state(run_dir)["state"], "waiting")
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_changed_checkout_keeps_the_checked_head_without_a_round_row(self):
        lp, owner, base, lines, _ = self.branch_unittest(self.root)
        wt = lp.wt
        lp.state["round_summaries"].clear()
        tip = self.move_target(owner, wt)
        run.git(wt, "rebase", tip)
        run.set_base(lp, tip)

        run.rounds(lp)
        self.assertEqual(lp.state["verdict"], "PASS")
        self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer"])
        self.repair.assert_not_called()
        self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
        self.assertNotEqual(record.read_state(lp.run_dir)["state"], "waiting")
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_check_green_on_the_old_base_and_red_on_the_tip_still_parks(self):
        _, owner, wt = red.make_repos(self.root)
        cmd = "test ! -f breakage"
        lp, run_dir, _ = red.make_loop(self.root, wt, ["true", f"{cmd}  # once"])
        base = run.git(wt, "merge-base", "HEAD", "origin/main")
        self.assertTrue(gate.run_done_when([cmd], wt, run_dir / "before.log", set())[0])
        self.move_target(owner, wt)
        self.assertTrue(run.integrate(lp, "origin/main"))
        (owner / "poison").touch()
        tip = self.move_target(owner, wt)
        self.assertTrue(run.integrate(lp, "origin/main"))
        head = run.git(wt, "rev-parse", "HEAD")

        self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, [])
        state = record.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["merge_note"], f"origin/main itself fails: `{cmd}`")
        self.assertEqual(state["waiting_on"]["sha"], tip)
        self.repair.assert_called_once()
        self.assertEqual(self.repair.call_args.kwargs["repair"]["sha"], tip)
        probes = (run_dir / "target-probe.log").read_text()
        self.assertEqual(probes.count(f"$ {cmd} (on "), 2)
        self.assertIn(base, probes)
        self.assertIn(tip, probes)
        self.assert_on_branch_head_and_clean(wt, head)

    def test_an_old_base_equal_to_the_tip_is_probed_only_once(self):
        _, _, wt = red.make_repos(self.root)
        lp, run_dir, _ = red.make_loop(self.root, wt, ["false  # once"])
        head = run.git(wt, "rev-parse", "HEAD")
        self.assertEqual(run.target_fails(lp, "origin/main", "$ false\n[exit 1]\n"), "`false`")
        self.assertEqual((run_dir / "target-probe.log").read_text().count("$ false (on "), 1)
        self.assert_on_branch_head_and_clean(wt, head)

    def test_a_lander_repairs_a_red_target_even_when_the_old_base_is_red(self):
        _, owner, wt = red.make_repos(self.root)
        cmd = "test ! -f breakage && test ! -f poison"
        (owner / "AGENTS.md").write_text(f"---\ntests: {cmd}\n---\n")
        base = self.move_target(owner, wt)
        run.git(wt, "rebase", base)
        run.git(wt, "rm", "breakage")
        run.git(wt, "commit", "-m", "fix the old red base")
        lp, directory, _ = red.make_loop(config.RUNS, wt, [f"{cmd}  # once"])
        (directory / "task.md").write_text(f"# Work\n\n## Done when\n```bash\n{cmd}  # once\n```\n")
        head = run.git(wt, "rev-parse", "HEAD")
        (owner / "poison").touch()
        tip = self.move_target(owner, wt)
        lp.state.update(state="waiting", waiting_on={
            "line": run.turn_path(lp, "origin/main").name, "joined": 1})
        lp.save()
        before = (directory / "run.json").read_bytes()
        with patch.object(watch, "launch_resume") as wake:
            land.check_line(run.turn_path(lp, "origin/main"))
        self.repair.assert_called_once()
        self.assertEqual(self.repair.call_args.kwargs["repair"]["sha"], tip)
        self.assertEqual((directory / "run.json").read_bytes(), before)
        wake.assert_not_called()
        probe = (directory / "target-probe.log").read_text()
        self.assertIn(f"Commit: {tip}", probe)
        self.assertNotIn(base, probe)
        self.assertEqual(probe.count(f"$ {cmd}\n"), 1)
        self.assertEqual(self.turns, [])
        self.assert_on_branch_head_and_clean(wt, head)

    def landing_review(self, root, once=True):
        _, owner, wt = red.make_repos(root)
        cmd = "test ! -f breakage && test ! -f poison"
        lp, run_dir, lines = red.make_loop(root, wt, [f"{cmd}  # once" if once else cmd])
        base = self.move_target(owner, wt)
        run.git(wt, "rebase", base)
        (wt / "breakage").unlink()
        run.git(wt, "add", "-A")
        run.git(wt, "commit", "-m", "fix breakage")
        lp.state["landing"] = True
        ok, text = run.verify_work(lp)
        self.assertTrue(ok)
        # A landing review skips the suite; only the final check advances its green head.
        self.assertEqual(run.review(lp, "Fixed breakage.", ok, text, record=False), "PASS")
        self.assertTrue(run.final_check(lp, "origin/main"))
        return lp, owner, base, lines, cmd

    def test_a_landing_review_without_a_round_row_keeps_its_old_base(self):
        lp, owner, base, lines, cmd = self.landing_review(self.root)
        wt, run_dir = lp.wt, lp.run_dir
        (owner / "poison").touch()
        tip = self.move_target(owner, wt)
        head = self.integrate(lp, tip)
        ok, text = gate.run_done_when([cmd], wt, run_dir / "failed.log", set())
        self.assertFalse(ok)
        self.assertEqual(run.target_fails(lp, "origin/main", text), "")
        self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
        self.repair.assert_not_called()
        self.assert_on_branch_head_and_clean(wt, head)

    def test_conflicts_keep_the_last_landing_review_base(self):
        for how in ("rebase", "merge"):
            with self.subTest(how=how):
                root = self.root / how
                root.mkdir()
                lp, owner, base, lines, cmd = self.landing_review(root, once=False)
                wt = lp.wt
                lp.state["merge_method"] = "merge" if how == "merge" else "squash"
                (owner / "poison").touch()
                (owner / "work.txt").write_text("target intent\n")
                self.move_target(owner, wt)
                self.turns.clear()

                def fix(lp, role, text, name, **_kw):
                    self.turns.append(name)
                    lp.round_dir.mkdir(parents=True, exist_ok=True)
                    if run.in_progress(wt, how):
                        (wt / "work.txt").write_text("both intents\n")
                        run.git(wt, "add", "work.txt")
                        if how == "rebase":
                            run.git(wt, "-c", "core.editor=true", "rebase", "--continue")
                        else:
                            run.git(wt, "commit", "-m", "resolve conflict")
                    else:
                        (wt / "poison").unlink()
                        run.git(wt, "add", "-A")
                        run.git(wt, "commit", "-m", "fix poison")
                    return "## Summary\nResolved the conflict and fixed the check."

                with patch.object(run, "execute", side_effect=fix):
                    self.assertTrue(run.integrate(lp, "origin/main"))
                self.assertEqual(self.turns, [f"{how}-fixer", "executor"])
                self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
                self.repair.assert_not_called()
                self.assertNotEqual(record.read_state(lp.run_dir)["state"], "waiting")
                self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_an_older_receipt_uses_its_last_passing_round(self):
        _, owner, wt = red.make_repos(self.root)
        cmd = "test ! -f breakage"
        lp, run_dir, _ = red.make_loop(self.root, wt, [f"{cmd}  # once"])
        tip = self.move_target(owner, wt)
        head = self.integrate(lp, tip)
        lp.state["review_pending"].pop("passed_head_sha", None)
        lp.state["round_summaries"].append({"verdict": "FAIL", "done_when": False,
                                            "head_sha": head})
        self.assertEqual(run.target_fails(lp, "origin/main", f"$ {cmd}\n[exit 1]\n"), f"`{cmd}`")
        self.assertEqual((run_dir / "target-probe.log").read_text().count(f"$ {cmd} (on "), 2)
        self.assert_on_branch_head_and_clean(wt, head)

    def test_both_probes_restore_the_branch_and_drop_generated_files(self):
        _, owner, wt = red.make_repos(self.root)
        (wt / "gen").write_text("branch generated\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch generated file")
        cmd = "python3 -c \"open('gen', 'a').write('probe'); exit(1)\""
        lp, run_dir, _ = red.make_loop(self.root, wt, [f"{cmd}  # once"])
        tip = self.move_target(owner, wt)
        head = self.integrate(lp, tip)
        real_git_out = run.git_out
        probes = []

        def checkout(repo, *args, **kwargs):
            if args[:3] == ("checkout", "--quiet", "--detach"):
                self.assert_on_branch_head_and_clean(wt, head)
                probes.append(args[-1])
            return real_git_out(repo, *args, **kwargs)

        with patch.object(run, "git_out", side_effect=checkout):
            self.assertEqual(run.target_fails(lp, "origin/main", f"$ {cmd}\n[exit 1]\n"), "")
        self.assertEqual(len(probes), 2)
        self.repair.assert_not_called()
        self.assertEqual((wt / "gen").read_text(), "branch generated\n")
        self.assert_on_branch_head_and_clean(wt, head)


if __name__ == "__main__":
    unittest.main()

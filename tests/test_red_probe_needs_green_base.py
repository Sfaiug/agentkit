"""A red tip can park a run only when the same check passed on its old target base.

Real commands and temporary git repos; the fixer and repair launcher are fakes.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_red_target as red
from agentkit import run


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

    def test_a_branch_only_unittest_module_runs_the_fixer_instead_of_parking(self):
        _, owner, wt = red.make_repos(self.root)
        (wt / "tests").mkdir()
        (wt / "tests/__init__.py").touch()
        (wt / "tests/test_new.py").write_text(
            "from pathlib import Path\nimport unittest\n\n"
            "class New(unittest.TestCase):\n"
            "    def test_no_breakage(self):\n"
            "        self.assertFalse(Path('breakage').exists())\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch unittest module")
        cmd = "python3 -m unittest tests.test_new"
        lp, run_dir, lines = red.make_loop(self.root, wt, ["true", f"{cmd}  # once"])
        base = run.git(wt, "merge-base", "HEAD", "origin/main")
        self.assertTrue(run.run_done_when([cmd], wt, run_dir / "before.log", set())[0])
        tip = self.move_target(owner, wt)
        self.integrate(lp, tip)

        self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer"])
        self.assertNotEqual(run.read_state(run_dir)["state"], "waiting")
        self.repair.assert_not_called()
        self.assertIn(f"fails on {base[:12]} too: needs this branch", "\n".join(lines))
        probes = (run_dir / "target-probe.log").read_text()
        self.assertEqual(probes.count(f"$ {cmd} (on "), 2)
        self.assertIn(tip, probes)
        self.assertIn(base, probes)
        self.assert_on_branch_head_and_clean(wt, run.git(wt, "rev-parse", "HEAD"))

    def test_a_check_green_on_the_old_base_and_red_on_the_tip_still_parks(self):
        _, owner, wt = red.make_repos(self.root)
        cmd = "test ! -f breakage"
        lp, run_dir, _ = red.make_loop(self.root, wt, ["true", f"{cmd}  # once"])
        base = run.git(wt, "merge-base", "HEAD", "origin/main")
        self.assertTrue(run.run_done_when([cmd], wt, run_dir / "before.log", set())[0])
        tip = self.move_target(owner, wt)
        head = self.integrate(lp, tip)

        self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, [])
        state = run.read_state(run_dir)
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

    def landing_review(self, root, once=True):
        _, owner, wt = red.make_repos(root)
        cmd = "test ! -f breakage && test ! -f poison"
        lp, run_dir, lines = red.make_loop(root, wt, [f"{cmd}  # once" if once else cmd])
        base = self.move_target(owner, wt)
        run.git(wt, "rebase", base)
        (wt / "breakage").unlink()
        run.git(wt, "add", "-A")
        run.git(wt, "commit", "-m", "fix breakage")
        self.assertTrue(run.run_done_when([cmd], wt, run_dir / "before.log", set())[0])
        # Landing reviews replace review without appending to round_summaries.
        lp.state["review"].update(run.commit_identity(wt))
        return lp, owner, base, lines, cmd

    def test_a_landing_review_without_a_round_row_keeps_its_old_base(self):
        lp, owner, base, lines, cmd = self.landing_review(self.root)
        wt, run_dir = lp.wt, lp.run_dir
        (owner / "poison").touch()
        tip = self.move_target(owner, wt)
        head = self.integrate(lp, tip)
        ok, text = run.run_done_when([cmd], wt, run_dir / "failed.log", set())
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
                self.assertNotEqual(run.read_state(lp.run_dir)["state"], "waiting")
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

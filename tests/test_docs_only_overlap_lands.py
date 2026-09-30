"""A target that moved under a landing sharing only docs with the branch lands after the done-when.

Offline: real throwaway git repos under a temp dir with a bare `origin`, fake done-when
commands that record what they saw, and a temporary HOME. No network, no real harness: a
clean integration keeps its review, so no fixer or reviewer runs. The target moves while
the first lap verifies, as another run's merge moves it.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

GUIDE = "docs/guide.md"
NOTES = "docs/über.md"      # git quotes it unless asked not to
CODE = "\tapp.py"          # git() would trim the tab off a list's first path
LINES = "1\n2\n3\n4\n5\n"


def commit(cwd, edits, message):
    for name, text in edits.items():
        (cwd / name).parent.mkdir(parents=True, exist_ok=True)
        (cwd / name).write_text(text)
    run.git(cwd, "add", ".")
    run.git(cwd, "commit", "-m", message)


def make_origin(root):
    """A bare origin and an owner clone that moves it, standing in for GitHub."""
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    run.git(owner, "config", "user.name", "fixture")
    run.git(owner, "config", "user.email", "fixture@localhost")
    commit(owner, {GUIDE: LINES, NOTES: LINES, CODE: LINES}, "base")
    run.git(owner, "push", "origin", "main")
    return remote, owner


def make_run(root, remote, name, cmds, edits):
    """A passed run of `remote` on ak/<name>, its record in the runs directory."""
    wt = root / name
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", f"ak/{name}")
    commit(wt, edits, name)
    run_dir = config.RUNS / f"{root.name}-{name}"
    run_dir.mkdir(parents=True)
    (run_dir / "log.txt").touch()
    head = run.git(wt, "rev-parse", "HEAD")
    tree = run.git(wt, "rev-parse", "HEAD^{tree}")
    cfg = config.load()
    executor_provider, reviewer_provider = run.review_providers(cfg, "opus", "astra")

    def log(msg):
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(f"[00:00:00] {msg}\n")

    state = {
        "run_id": run_dir.name, "title": name, "state": "running", "verdict": "PASS",
        **run.process_owner(), "started_at": time.time(),
        "review": {"executor": "opus", "executor_provider": executor_provider,
                   "reviewer": "astra", "reviewer_provider": reviewer_provider,
                   "returncode": 0, "verdict": "PASS", "done_when": True,
                   "head_sha": head, "tree_sha": tree},
        "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                             "summary": "work", "head_sha": head, "tree_sha": tree}],
        "rounds": 3, "base": "origin/main", "target": "origin/main",
        "base_sha": run.git(wt, "rev-parse", "origin/main^{commit}"), "branch": f"ak/{name}",
        "worktree": str(wt), "repo": str(wt), "executor": "opus", "reviewer": "astra",
        "merge_method": "squash", "merged": False, "merge_failed": False,
        "merge_note": None, "findings": "",
    }
    run.save_state(run_dir, state)
    return run.Loop(cfg, run_dir, state, {}, log, wt, "body", cmds, "context", [])


class DocsOnlyOverlapLands(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".docs-overlap-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.counter = self.root / "counter"
        self.counter.touch()
        self.pickups = []
        self.stack.enter_context(patch.object(
            run, "pickup_new_code",
            side_effect=lambda lp, **kw: self.pickups.append(kw.get("extra")) or False))
        self.stack.enter_context(patch.object(
            run, "execute", side_effect=AssertionError("unexpected fixer turn")))
        self.stack.enter_context(patch.object(
            run, "call_retrying", side_effect=AssertionError("unexpected reviewer turn")))
        self.delivered = []

    def cmds(self, check="true"):
        return [f"echo every $(git rev-parse HEAD) >> {self.counter}; {check}",
                f"echo once $(git rev-parse HEAD) >> {self.counter}  # once"]

    def land(self, lp, owner, moves, later=None):
        """Land `lp`; while its first lap verifies, the owner pushes `moves` to main."""
        laps = []

        def verify():
            laps.append(True)
            if len(laps) > 1 and later:
                return later()
            ok = run.integrate(lp, "origin/main") and run.final_check(lp, "origin/main")
            if len(laps) == 1:
                commit(owner, moves, "main moves")
                run.git(owner, "push", "origin", "main")
            return ok

        return run.land(lp, "origin/main", verify, lambda: self.delivered.append(True) or True,
                        execv=lambda *a: self.fail("no pickup here"))

    def rows(self):
        return [line.split() for line in self.counter.read_text().splitlines()]

    def assert_untracked(self, lp, name):
        self.assertTrue((lp.wt / name).exists(), f"{name} is gone")
        self.assertEqual(run.git(lp.wt, "ls-files", name), "", f"{name} was committed")

    def test_docs_only_overlap_lands_after_the_done_when_without_a_reserved_lap(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "acme", self.cmds(),
                      {GUIDE: "acme\n2\n3\n4\n5\n", NOTES: "acme\n2\n3\n4\n5\n",
                       "acme.py": "acme\n"})
        (lp.wt / "extra.py").write_text("unreviewed\n")
        self.assertTrue(self.land(lp, owner, {GUIDE: "1\n2\n3\n4\nfive\n",
                                              NOTES: "1\n2\n3\n4\nfive\n"}))
        self.assert_untracked(lp, "extra.py")
        self.assertEqual(self.delivered, [True])
        self.assertEqual(self.pickups, [{"land_lap": 1}])
        head = run.git(lp.wt, "rev-parse", "HEAD")
        tip = run.git(owner, "rev-parse", "main^{commit}")
        self.assertEqual(run.git_out(lp.wt, "merge-base", "--is-ancestor", tip, "HEAD")[0], 0)
        self.assertEqual((lp.wt / GUIDE).read_text(), "acme\n2\n3\n4\nfive\n")
        # the done-when ran again on the landed commit; the once-command did not
        self.assertEqual([row[0] for row in self.rows()], ["every", "once", "every"])
        self.assertEqual(self.rows()[-1][1], head)
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["base_sha"], tip)
        self.assertEqual(state["review"]["head_sha"], head)
        self.assertEqual(state["verdict"], "PASS")
        self.assertNotIn("review_pending", state)
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn("origin/main moved, overlapping this branch only in docs "
                      "(docs/guide.md, docs/über.md); landing after the done-when", log)
        self.assertNotIn("verifying again holding the merge turn", log)

    def test_docs_only_overlap_whose_done_when_fails_does_not_land(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "bravo",
                      self.cmds(f"! grep -q broken {GUIDE}"),
                      {GUIDE: "bravo\n2\n3\n4\n5\n", "bravo.py": "bravo\n"})
        (lp.wt / "extra.py").write_text("unreviewed\n")
        head = run.git(lp.wt, "rev-parse", "HEAD")
        verified = lp.base_sha
        seen = {}

        def reserved_lap():
            seen.update(head=run.git(lp.wt, "rev-parse", "HEAD"), base=lp.base_sha,
                        review=lp.state["review"]["head_sha"])
            return False

        self.assertFalse(self.land(lp, owner, {GUIDE: "1\n2\n3\n4\nbroken\n"}, reserved_lap))
        self.assertEqual(self.delivered, [])
        self.assertEqual(self.pickups, [{"land_lap": 1}, {"land_lap": 2}])
        # the reserved lap starts from the verified commit, its review intact
        self.assertEqual(seen, {"head": head, "base": verified, "review": head})
        self.assert_untracked(lp, "extra.py")
        self.assertEqual([row[0] for row in self.rows()].count("once"), 1)
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn("done-when after the rebase: FAILED", log)
        self.assertIn("verifying again holding the merge turn", log)

    def test_docs_edit_already_on_the_target_is_not_delivered(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "delta", self.cmds(), {GUIDE: "delta\n2\n3\n4\n5\n"})
        self.assertFalse(self.land(lp, owner, {GUIDE: "delta\n2\n3\n4\n5\n"}))
        self.assertEqual(self.delivered, [])
        self.assertTrue(run.read_state(lp.run_dir).get("on_target"))
        self.assertIn("its work is already on main", (lp.run_dir / "log.txt").read_text())

    def test_code_overlap_takes_the_reserved_lap(self):
        remote, owner = make_origin(self.root)
        # the branch's own first path sorts before the shared code file, main's does not
        lp = make_run(self.root, remote, "gizmo", self.cmds(),
                      {GUIDE: "gizmo\n2\n3\n4\n5\n", CODE: "gizmo\n2\n3\n4\n5\n",
                       "\t0.md": "gizmo\n"})
        self.assertTrue(self.land(lp, owner, {GUIDE: "1\n2\n3\n4\nfive\n",
                                              CODE: "1\n2\n3\n4\nfive\n"}))
        self.assertEqual(self.delivered, [True])
        self.assertEqual(self.pickups, [{"land_lap": 1}, {"land_lap": 2}])
        # the reserved lap runs the heavy suite again
        self.assertEqual([row[0] for row in self.rows()], ["every", "once", "every", "once"])
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn("touching this branch's files; verifying again holding the merge turn", log)
        self.assertNotIn("only in docs", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)

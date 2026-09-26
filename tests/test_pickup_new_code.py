"""A run in flight picks up merged loop code at its next step, keeping its slot.  Offline.

Temporary HOME, fake run records and an injected exec callable; no test execs or
signals a real process.  The install is faked as two short commits, the move as the
old one giving way to the new one at a round or landing boundary.  Held turns are the
real `gate_turn` and `merge_turn`, taken without contention under the temporary HOME.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker

OLD = "aaa1111"
NEW = "bbb2222"


class PickupNewCode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".pickup-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_DISCORD_WEBHOOK": "off"}))
        config.ensure_dirs()
        self.old_start = run._PICKUP_START
        run._PICKUP_START = None
        self.old_held = getattr(run._PICKUP_HELD, "count", None)
        run._PICKUP_HELD.count = 0
        self.addCleanup(self.restore_pickup)

    def restore_pickup(self):
        run._PICKUP_START = self.old_start
        if self.old_held is None:
            try:
                delattr(run._PICKUP_HELD, "count")
            except AttributeError:
                pass
        else:
            run._PICKUP_HELD.count = self.old_held

    def make_scratch(self, name, passed=False, rounds=3):
        """A fake scratch run of invented acme work, its record on disk, as a Loop."""
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        (run_dir / "task.md").write_text(
            "# Acme fix\n\nWork: fix-api\n\n## Done when\n```bash\ntrue\n```\n")
        wt = config.WORK / name
        wt.mkdir(parents=True, exist_ok=True)
        cfg = config.load()
        exec_prov, rev_prov = run.review_providers(cfg, "opus", "astra")

        def log(msg):
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(f"[00:00:00] {msg}\n")

        state = {
            "run_id": name, "title": "Acme fix", "state": "running", "verdict": None,
            **run.process_owner(), "started_at": time.time(),
            "repo": None, "scratch": True, "base": None, "target": None, "base_sha": None,
            "branch": None, "worktree": str(wt), "executor": "opus", "reviewer": "astra",
            "rounds": rounds, "round_summaries": [], "findings": "",
            "merge_method": "squash", "merged": False, "merge_failed": False,
            "merge_note": None,
        }
        if passed:
            state.update(
                verdict="PASS",
                review={"executor": "opus", "executor_provider": exec_prov,
                        "reviewer": "astra", "reviewer_provider": rev_prov,
                        "returncode": 0, "verdict": "PASS", "done_when": True},
                round_summaries=[{"round": 1, "verdict": "PASS", "done_when": True,
                                  "summary": "work"}])
        run.save_state(run_dir, state)
        return run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])

    def make_repo_run(self, name):
        """A fake passed run of invented acme work with a worktree, as a Loop.

        No real git: the landings below stub every git call, so the test never
        leaves its temporary HOME.
        """
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        (run_dir / "task.md").write_text(
            "# Acme fix\n\nWork: fix-api\n\n## Done when\n```bash\ntrue\n```\n")
        wt = self.root / f"wt-{name}"
        wt.mkdir(parents=True)
        cfg = config.load()
        exec_prov, rev_prov = run.review_providers(cfg, "opus", "astra")

        def log(msg):
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(f"[00:00:00] {msg}\n")

        state = {
            "run_id": name, "title": "Acme fix", "state": "running", "verdict": "PASS",
            **run.process_owner(), "started_at": time.time(),
            "repo": str(wt), "scratch": False, "base": "main", "target": "origin/main",
            "base_sha": "base0001", "branch": "ak/acme-fix", "worktree": str(wt),
            "executor": "opus", "reviewer": "astra", "rounds": 3,
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": "work", "head_sha": "head0001",
                                 "tree_sha": "tree0001"}],
            "findings": "",
            "review": {"executor": "opus", "executor_provider": exec_prov,
                       "reviewer": "astra", "reviewer_provider": rev_prov,
                       "returncode": 0, "verdict": "PASS", "done_when": True,
                       "head_sha": "head0001", "tree_sha": "tree0001"},
            "merge_method": "squash", "merged": False, "merge_failed": False,
            "merge_note": None,
        }
        run.save_state(run_dir, state)
        return run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])

    def test_moved_install_execs_resume_and_same_pid_is_not_queued(self):
        lp = self.make_scratch("pickup-one", rounds=1)
        run._PICKUP_START = OLD
        calls, order = [], []

        def fake_exec(path, argv):
            order.append("exec")
            calls.append((path, argv))

        def fake_execute(lp2, role, text, name):
            order.append("work")
            return "## Summary\nWork."

        with patch.object(run, "installed_head", return_value=NEW), \
                patch.object(run, "execute", side_effect=fake_execute), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]\n")), \
                patch.object(run, "review", return_value="FAIL"):
            run.rounds(lp, execv=fake_exec)
        self.assertEqual(len(calls), 1)
        path, argv = calls[0]
        self.assertEqual(path, sys.executable)
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("bin/ak"))
        self.assertEqual(argv[2:], ["run", "resume", "pickup-one"])
        self.assertEqual(order[0], "exec")
        saved = run.read_state(lp.run_dir)
        self.assertEqual(saved["pickup"],
                         {"pid": saved["pid"], "from": OLD, "to": NEW})
        # the same pid still owns its slot: admission returns it at once, unqueued
        admitted = run.wait_for_slot(lp.run_dir)
        self.assertEqual(admitted["state"], "running")
        self.assertFalse(admitted.get("slot_waiting"))
        # and the resume it exec'd to continues in place, on the new code
        seen = {}

        def fake_drive(cfg, run_dir, opts, log, prior=None, job=None):
            seen["prior"] = dict(prior) if prior else None
            return 0

        with patch.object(run, "drive", side_effect=fake_drive), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.resume_run(["pickup-one"]), 0)
        self.assertEqual(seen["prior"]["state"], "running")
        self.assertNotIn("resume_from", seen["prior"])
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["state"], "running")
        self.assertFalse(state.get("slot_waiting"))
        self.assertNotIn("pickup", state)
        self.assertIn(f"picked up agentkit {OLD}..{NEW}; continuing on it",
                      (lp.run_dir / "log.txt").read_text())

    def test_no_exec_when_unmoved_or_a_turn_or_child_is_held(self):
        lp = self.make_scratch("pickup-two")
        calls = []

        def fake_exec(path, argv):
            calls.append((path, argv))

        run._PICKUP_START = OLD
        self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=OLD))
        self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=""))
        with patch.object(run, "installed_head",
                          side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10)):
            self.assertFalse(run.pickup_new_code(lp, execv=fake_exec))
        state = run.read_state(lp.run_dir)
        state["gate_turn"] = {"pid": state["pid"], "of": "acme"}
        run.save_state(lp.run_dir, state)
        lp.state = state
        self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        state.pop("gate_turn", None)
        state["merge_turn"] = {"pid": state["pid"], "of": "acme main"}
        run.save_state(lp.run_dir, state)
        lp.state = state
        self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        state.pop("merge_turn", None)
        run.save_state(lp.run_dir, state)
        lp.state = state
        # a turn this thread really holds, gate or merge, blocks the move too
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        gated = config.RUNS / "pickup-gated"
        gated.mkdir()
        run.save_state(gated, {"run_id": "pickup-gated", "title": "gated",
                               "state": "running", "verdict": None,
                               "repo": "/home/fixture/code/acme", **run.process_owner(),
                               "started_at": time.time(), "round_summaries": []})
        with patch.dict(os.environ, {"AK_MAX_RUNS": "4"}):
            with run.gate_turn(gated, gated / "gate.log", lambda msg: None):
                self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        with run.merge_turn(lp, "origin/main"):
            self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        self.assertEqual(getattr(run._PICKUP_HELD, "count", 0), 0)
        with patch.object(worker, "marked_pids", return_value=[12345]):
            self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        # a process driving more than this run never replaces itself for one task
        box = {}

        def in_thread():
            box["moved"] = run.pickup_new_code(lp, execv=fake_exec, current=NEW)

        thread = threading.Thread(target=in_thread, daemon=True)
        thread.start()
        thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertFalse(box["moved"])
        with run.job_muted():
            self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        lp.no_pickup = True
        try:
            self.assertFalse(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        finally:
            del lp.no_pickup
        self.assertEqual(calls, [])
        self.assertNotIn("pickup", run.read_state(lp.run_dir))
        self.assertEqual(run._PICKUP_START, OLD)
        # and with nothing held, the same boundary moves
        self.assertTrue(run.pickup_new_code(lp, execv=fake_exec, current=NEW))
        self.assertEqual(len(calls), 1)

    def test_passed_run_keeps_its_pass_through_the_move(self):
        lp = self.make_repo_run("pickup-three")
        cfg = config.load()
        self.assertTrue(run.review_pass(lp.state, cfg))
        run._PICKUP_START = OLD
        calls, order = [], []

        def fake_exec(path, argv):
            order.append("exec")
            calls.append((path, argv))

        def fake_verify():
            order.append("verify")
            return True

        with patch.object(run, "installed_head", return_value=NEW), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value=lp.base_sha):
            self.assertTrue(run.land(lp, "origin/main", fake_verify, lambda: True,
                                     execv=fake_exec))
        self.assertEqual(len(calls), 1)
        self.assertEqual(order[:2], ["exec", "verify"])
        self.assertEqual(getattr(run._PICKUP_HELD, "count", 0), 0)
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["verdict"], "PASS")
        self.assertTrue(run.review_pass(state, cfg))
        seen = {}

        def fake_drive(cfg, run_dir, opts, log, prior=None, job=None):
            seen["prior"] = dict(prior) if prior else None
            return 0

        with patch.object(run, "drive", side_effect=fake_drive), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.resume_run(["pickup-three"]), 0)
        self.assertEqual(seen["prior"]["verdict"], "PASS")
        self.assertEqual(seen["prior"]["review"]["verdict"], "PASS")
        kept = run.read_state(lp.run_dir)
        self.assertEqual(kept["verdict"], "PASS")
        self.assertTrue(run.review_pass(kept, cfg))
        self.assertIn(f"picked up agentkit {OLD}..{NEW}; continuing on it",
                      (lp.run_dir / "log.txt").read_text())

    def test_landing_keeps_its_lap_count_across_the_move(self):
        lp = self.make_repo_run("pickup-four")
        run._PICKUP_START = OLD
        calls = []

        def fake_exec(path, argv):
            calls.append((path, argv))

        self.assertTrue(run.pickup_new_code(lp, execv=fake_exec, current=NEW,
                                            extra={"land_lap": 2}))
        self.assertEqual(run.read_state(lp.run_dir)["pickup"]["land_lap"], 2)
        seen = {}

        def fake_drive(cfg, run_dir, opts, log, prior=None, job=None):
            seen["prior"] = dict(prior) if prior else None
            return 0

        with patch.object(run, "drive", side_effect=fake_drive), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.resume_run(["pickup-four"]), 0)
        self.assertEqual(seen["prior"]["land_lap"], 2)
        # the new code verifies laps 2 and 3, then parks, instead of three fresh laps
        lp.state = run.read_state(lp.run_dir)
        run._PICKUP_START = NEW
        verifies = []

        def fake_verify():
            verifies.append(1)
            return True

        with patch.object(run, "installed_head", return_value=NEW), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value="tip9999"), \
                patch.object(run, "disjoint_move", return_value=False):
            self.assertFalse(run.land(
                lp, "origin/main", fake_verify,
                lambda: self.fail("a twice-moved target parks, never lands"),
                execv=fake_exec))
        self.assertEqual(len(verifies), 2)
        self.assertEqual(len(calls), 1)
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertIn("moved three times", state["merge_note"])
        self.assertNotIn("land_lap", state)

    def test_stale_pickup_with_a_reused_pid_queues_normally(self):
        lp = self.make_scratch("pickup-five")
        state = run.read_state(lp.run_dir)
        state["process_identity"] = {"boot": "dead-boot", "ticks": -1}
        state["pickup"] = {"pid": os.getpid(), "from": OLD, "to": NEW}
        run.save_state(lp.run_dir, state)
        seen = {}

        def fake_drive(cfg, run_dir, opts, log, prior=None, job=None):
            seen["prior"] = dict(prior) if prior else None
            return 0

        with patch.object(run, "drive", side_effect=fake_drive), \
                patch.object(run, "stop_run_tree"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.resume_run(["pickup-five"]), 0)
        self.assertTrue(seen["prior"]["slot_waiting"])
        self.assertEqual(seen["prior"]["resume_from"], "interrupted")
        self.assertEqual(run.read_state(lp.run_dir)["state"], "queued")
        self.assertNotIn("picked up agentkit", (lp.run_dir / "log.txt").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)

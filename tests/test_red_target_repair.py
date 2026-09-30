"""A red target starts its own repair, and the runs parked on it retry when that repair ends.

Real throwaway git repos under a temp dir with a bare `origin`, a temporary HOME, and fakes
for the launch (`prepare`, `spawn_bg`), the seat and the fetch: no real run, seat or tmux.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_red_target as red
from agentkit import config, run, watch

FAILS = "echo 'FAIL 49 harness names 306 > 305'; exit 1"
QUESTION = "Should main keep 306 harness names or drop one?"
SPAWN_BG = run.spawn_bg


class RedTargetRepair(unittest.TestCase):
    fixer = red.RedTarget.fixer
    review_call = red.RedTarget.review_call

    def setUp(self):
        red.RedTarget.setUp(self)
        self.prepared, self.spawned, self.logs = [], [], []
        self.stack.enter_context(patch.object(run, "prepare", side_effect=self.prepare))
        self.stack.enter_context(patch.object(run, "spawn_bg", side_effect=self.spawn))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        for seat in ("seat", "other"):
            config.session_path(seat).write_text("{}")

    def prepare(self, directory, opts, log, cfg, *args, **kwargs):
        # what preflight leaves: a receipt queued for a slot, `first` from the options
        self.prepared.append((directory.name, dict(opts)))
        run.save_state(directory, {**run.read_state(directory), "run_id": directory.name,
                                   "state": "queued", "slot_waiting": True,
                                   **({"first": True} if opts.get("--first") else {})})

    def spawn(self, run_dir, argv, expected=None, park_as=False):
        self.spawned.append((run_dir.name, argv))
        return 0

    def move(self, owner):
        """The target's next commit, as red as the last; the work branch rebased onto it."""
        with (owner / "more.txt").open("a") as fh:
            fh.write("more\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "more")
        run.git(owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        run.git(self.wt, "rebase", "origin/main")
        return run.git(owner, "rev-parse", "HEAD")

    def red_run(self, where, seat, cmds=(f"{FAILS}  # once",)):
        """A run of `seat` whose final check fails on origin/main's own tip; parked."""
        lp, run_dir, _ = red.make_loop(self.root / where, self.wt, ["true", *cmds])
        lp.state["launched_session"] = seat
        self.assertFalse(run.final_check(lp, "origin/main"))
        return run.read_state(run_dir)

    def test_the_first_run_on_a_red_target_starts_one_repair_and_the_rest_wait_on_it(self):
        _, owner, self.wt = red.make_repos(self.root)
        tip = run.git(owner, "rev-parse", "HEAD")
        first = self.red_run("first", "seat")
        self.assertEqual(first["state"], "waiting")
        self.assertEqual(self.turns, [])
        self.assertEqual(len(self.prepared), 1)
        name, opts = self.prepared[0]
        self.assertTrue(opts["--first"])
        self.assertEqual(self.spawned, [(name, [str(config.RUNS / name / "task.md")])])
        self.assertEqual(first["waiting_on"], {"ref": "origin/main", "sha": tip, "repair": name})
        repair = run.read_state(config.RUNS / name)
        self.assertEqual(repair["repair"], {"target": "main", "command": FAILS})
        self.assertEqual(repair["launched_session"], "seat")
        self.assertTrue(repair["first"])
        task = (config.RUNS / name / "task.md").read_text()
        for said in (f"`{FAILS}`", tip, "FAIL 49 harness names 306 > 305", "target: main",
                     f"## Done when\n```bash\n{FAILS}  # once\n```"):
            self.assertIn(said, task)
        # another seat's run on the same red parks on the repair already open
        second = self.red_run("second", "other")
        self.assertEqual(second["waiting_on"]["repair"], name)
        self.assertEqual(len(self.prepared), 1)
        # another command is another repair
        third = self.red_run("third", "other", cmds=("false  # once",))
        self.assertEqual(len(self.prepared), 2)
        self.assertEqual(third["waiting_on"]["repair"], self.prepared[1][0])
        self.assertEqual(run.read_state(config.RUNS / self.prepared[1][0])["repair"],
                         {"target": "main", "command": "false"})
        # a repair that ended guards nothing: the next run on the same red starts another
        run.save_state(config.RUNS / name, {**repair, "state": "not_needed",
                                            "not_needed": "passes now"})
        fourth = self.red_run("fourth", "seat")
        self.assertEqual(len(self.prepared), 3)
        self.assertEqual(fourth["waiting_on"]["repair"], self.prepared[2][0])

    def test_a_repair_run_fixes_its_own_red_instead_of_parking_on_it(self):
        _, _, self.wt = red.make_repos(self.root)
        lp, run_dir, _ = red.make_loop(self.root, self.wt, ["true", "false  # once"])
        lp.state.update(launched_session="seat", repair={"target": "main", "command": "false"})
        self.assertEqual(run.target_fails(lp, "origin/main", "$ false\n[exit 1]\n"), "")
        self.assertFalse((run_dir / "target-probe.log").exists())
        self.assertEqual(self.prepared, [])

    def parked(self, sha, repair):
        wt = self.root / "wt-parked"
        wt.mkdir(exist_ok=True)
        run_dir = config.RUNS / "20260930-0200-parked"
        run_dir.mkdir(parents=True, exist_ok=True)
        run.save_state(run_dir, {
            "run_id": run_dir.name, "state": "waiting", "verdict": "PASS",
            "launched_session": "seat", "worktree": str(wt), "finished_at": time.time(),
            "merge_note": "origin/main itself fails: `false`",
            "waiting_on": {"ref": "origin/main", **({"sha": sha} if sha else {}),
                           "repair": repair}})
        return run_dir

    def test_parked_runs_retry_when_their_repair_ends_merged_or_not(self):
        sha = "0" * 40
        repair = config.RUNS / "20260930-0201-repair"
        repair.mkdir(parents=True)
        base = {"run_id": repair.name, "launched_session": "seat",
                "repair": {"target": "main", "command": "false"},
                "followup": {"run": "parked", "text": "`false` fails", "place": "`false`"}}
        with patch.object(run, "upstream_sha", return_value=sha):
            run.save_state(repair, {**base, "state": "running"})
            run_dir = self.parked(sha, repair.name)
            watch.resume_waiting(log=self.logs.append)
            self.assertEqual(self.spawned, [])
            for ending in ({"state": "pass", "merged": True}, {"state": "fail"},
                           {"state": "not_needed", "not_needed": "passes now"}):
                with self.subTest(**ending):
                    self.spawned.clear()
                    run.save_state(repair, {**base, **ending})
                    run_dir = self.parked(sha, repair.name)
                    watch.resume_waiting(log=self.logs.append)
                    self.assertEqual(self.spawned, [(run_dir.name, ["resume", run_dir.name])])
                    self.assertIn(f"resumed {run_dir.name}: its repair {repair.name} ended",
                                  self.logs)
            # parked with no sha to wait from: the pass that takes one keeps the repair
            self.spawned.clear()
            run.save_state(repair, {**base, "state": "running"})
            run_dir = self.parked(None, repair.name)
            watch.resume_waiting(log=self.logs.append)
            self.assertEqual(run.read_state(run_dir)["waiting_on"],
                             {"ref": "origin/main", "sha": sha, "repair": repair.name})
            run.save_state(repair, {**base, "state": "fail"})
            watch.resume_waiting(log=self.logs.append)
            self.assertEqual(self.spawned, [(run_dir.name, ["resume", run_dir.name])])

    def test_a_repair_tells_its_seat_only_what_needs_somebody(self):
        run_dir = config.RUNS / "20260930-0202-repair"
        run_dir.mkdir(parents=True)
        base = {"run_id": run_dir.name, "launched_session": "seat",
                "started_at": time.time() - 60, "finished_at": time.time(),
                "repair": {"target": "main", "command": "false"},
                "followup": {"run": "parked", "text": "`false` fails", "place": "`false`"}}
        endings = {"merged": {"state": "pass", "verdict": "PASS", "merged": True},
                   "not needed": {"state": "not_needed", "not_needed": "passes now"},
                   "blocked": {"state": "blocked", "verdict": "BLOCKED", "error": QUESTION,
                               "blocked": f"## Blocked\n{QUESTION}"},
                   "failed": {"state": "fail", "verdict": "FAIL"}}
        for word, ending in endings.items():
            for live in (True, False):
                state = {**base, **ending}
                run.save_state(run_dir, state)

                @contextmanager
                def world(session):
                    yield live
                with self.subTest(word, live=live), \
                        patch.object(run, "launcher_world", world), \
                        patch.object(run, "hand_back") as hand_back, \
                        patch.object(watch, "revive", return_value=None) as revive, \
                        patch.object(run.notify, "shaped") as shaped:
                    run.announce(dict(state), run_dir, self.logs.append)
                    told = word in ("blocked", "failed")
                    self.assertEqual(hand_back.called, told and live)
                    self.assertEqual(revive.called, told and not live)
                    shaped.assert_not_called()

    def test_a_blocked_repair_asks_its_seat_and_holds_its_command_while_its_tip_stands(self):
        _, owner, self.wt = red.make_repos(self.root)
        self.red_run("first", "seat")
        name = self.prepared[0][0]
        repair = config.RUNS / name
        # queued at one tip, the repair starts on the next, and its question is about that one
        tip = self.move(owner)
        blocked = {**run.read_state(repair), "state": "blocked", "verdict": "BLOCKED",
                   "base_sha": tip, "error": QUESTION, "blocked": f"## Blocked\n{QUESTION}",
                   "started_at": time.time() - 60, "finished_at": time.time()}
        run.save_state(repair, blocked)

        @contextmanager
        def world(session):
            yield True
        with patch.object(run, "launcher_world", world), \
                patch.object(run, "hand_back") as hand_back:
            run.announce(dict(blocked), repair, self.logs.append)
        hand_back.assert_called_once()
        self.assertEqual(hand_back.call_args.args[0]["error"], QUESTION)
        # its waiter, retried on that unchanged tip, waits on the same question
        again = self.red_run("first", "seat")
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(again["waiting_on"], {"ref": "origin/main", "sha": tip, "repair": name})
        # and the tick leaves it parked there until the target moves
        self.spawned.clear()
        waiter = self.parked(tip, name)
        with patch.object(run, "upstream_sha", return_value=tip):
            watch.resume_waiting(log=self.logs.append)
        self.assertEqual(self.spawned, [])
        # a target that moved is a new question: the next run on its red repairs it again
        moved = self.move(owner)
        with patch.object(run, "upstream_sha", return_value=moved):
            watch.resume_waiting(log=self.logs.append)
        self.assertEqual(self.spawned[:1], [(waiter.name, ["resume", waiter.name])])
        later = self.red_run("later", "seat")
        self.assertEqual(len(self.prepared), 2)
        self.assertEqual(later["waiting_on"],
                         {"ref": "origin/main", "sha": moved, "repair": self.prepared[1][0]})

    def test_a_repair_whose_launch_raised_but_stayed_queued_is_still_waited_on(self):
        _, owner, self.wt = red.make_repos(self.root)
        tip = run.git(owner, "rev-parse", "HEAD")
        with patch.object(run, "spawn_bg", SPAWN_BG), \
                patch.object(run.orch, "start_in_slice", side_effect=OSError("no user bus")):
            first = self.red_run("first", "seat")
        name = self.prepared[0][0]
        repair = run.read_state(config.RUNS / name)
        self.assertEqual((repair["state"], repair["slot_waiting"]), ("queued", True))
        self.assertIn("no user bus", repair["launch_error"])
        self.assertEqual(first["waiting_on"], {"ref": "origin/main", "sha": tip, "repair": name})
        # the queued receipt is the repair: the next run on the same red parks on it too
        self.assertEqual(self.red_run("second", "other")["waiting_on"]["repair"], name)
        self.assertEqual(len(self.prepared), 1)
        waiter = self.parked(tip, name)
        with patch.object(run, "upstream_sha", return_value=tip):
            watch.resume_waiting(log=self.logs.append)
            self.assertEqual(self.spawned, [])
            run.save_state(config.RUNS / name, {**repair, "state": "fail"})
            watch.resume_waiting(log=self.logs.append)
        self.assertEqual(self.spawned, [(waiter.name, ["resume", waiter.name])])


if __name__ == "__main__":
    unittest.main()

"""A dead loop resumes itself where it stopped, continuing the open turn.

Offline: fake run directories, a dead pid that is never signalled, and a fake adapter
recording the session id and prompt of every turn it is asked for. The real adapters
are run once, against fake harness binaries, for the resume spelling each harness
takes. No tmux, no webhook, no model call.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run, watch

ADAPTER = """#!{python}
import json, os, sys
from pathlib import Path
record = Path(os.environ["RESUME_FIXTURE"]) / "calls.jsonl"
if len(sys.argv) < 2:
    sys.exit(2)
if sys.argv[1] == "auth":
    print("token file")
    sys.exit(0)
if sys.argv[1] == "usage":
    print(json.dumps({{"meters": [{{"name": "weekly", "used": 0}}]}}))
    sys.exit(0)
if sys.argv[1] != "run":
    sys.exit(2)
prompt = Path(sys.argv[5]).read_text()
out = Path(sys.argv[6])
sid = sys.argv[7] if len(sys.argv) > 7 else ""
out.mkdir(parents=True, exist_ok=True)
with record.open("a") as fh:
    fh.write(json.dumps({{"sid": sid, "prompt": prompt, "out": out.name}}) + "\\n")
if sid and sid == os.environ.get("RESUME_DIE", ""):
    sys.exit(1)
(out / "events.jsonl").write_text('{{"type": "result"}}\\n')
(out / "final.md").write_text(os.environ.get("RESUME_FINAL", "## Summary\\ncontinued\\n"))
(out / "session_id").write_text(sid or "fresh-session")
sys.exit(0)
"""


class ResumeMidturn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".resume-midturn-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        adapters = self.root / "adapters"
        adapters.mkdir()
        script = ADAPTER.format(python=sys.executable)
        for harness in ("claude", "codex", "muse"):
            path = adapters / f"{harness}.sh"
            path.write_text(script)
            path.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root),
            "AGENTKIT_ADAPTER_DIR": str(adapters),
            "RESUME_FIXTURE": str(self.root),
            "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX": "",
        }, clear=False))
        self.stack.enter_context(patch.object(run.time, "sleep", lambda _seconds: None))
        self.resumed = []
        self.stack.enter_context(patch.object(
            watch, "launch_resume",
            side_effect=lambda run_id, log=lambda _: None: self.resumed.append(run_id) or True))
        self.cards = []
        self.stack.enter_context(patch.object(
            notify, "shaped",
            side_effect=lambda *args, **kwargs: self.cards.append((args, kwargs)) or 0))
        self.stack.enter_context(patch.object(orch, "watching", return_value=False))
        self.stack.enter_context(patch.object(watch, "orphan_fresh", return_value=False))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        self.stack.enter_context(patch.object(watch, "seat_closed_by_owner", return_value=False))
        self.stack.enter_context(patch.object(run, "record_result", lambda *args, **kwargs: None))
        config.ensure_dirs()
        self.logs = []
        # the host's own clock: reap reads it directly, so the pass and the reap that
        # follows it in the same tick have to be measuring the same minutes
        self.now = time.time()

    def receipt(self, name, **extra):
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "log.txt").touch()
        work = config.WORK / name
        work.mkdir()
        state = {"run_id": name, "title": name, "state": "running", "pid": 2 ** 30,
                 "started_at": self.now - 100, "launched_session": "seat",
                 "executor": "opus", "reviewer": "astra", "rounds": 3,
                 "round_summaries": [], "step": "executor", "worktree": str(work),
                 "scratch": True, "base": None, **extra}
        run.save_state(directory, state)
        return directory

    def calls(self):
        path = self.root / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def tick(self, now=None):
        """One whole tick in its own order: the dead-loop pass, then the reap it ends with.

        The reap is where a dead pid becomes an interruption and a card, so a decision the
        pass made only in its own head would be undone here, in the same tick that made it.
        """
        watch.resume_dead_loops(dry_run=False, log=self.logs.append,
                                now=self.now if now is None else now)
        for directory in run.run_dirs():
            state = run.read_state(directory)
            if state:
                run.reap(directory, state)

    def loop(self, name, cmds=("true",)):
        directory = config.RUNS / name
        state = run.read_state(directory)
        work = Path(state["worktree"])
        lp = run.Loop(config.load(), directory, state, {}, self.logs.append, work,
                      "task body", list(cmds), "context line", [])
        lp.rnd = 1
        return lp

    def test_tick_resumes_a_dead_running_loop_and_the_session_stays_working(self):
        directory = self.receipt("20260922-1300-dead")
        self.tick()
        state = run.read_state(directory)
        self.assertNotIn("interrupted_at", state, "a record about to run again is not interrupted")
        self.assertNotIn("interruption_reason", state)
        self.assertEqual(self.resumed, [directory.name])
        self.assertEqual(state["state"], "running")
        self.assertFalse(state.get("recovery_pending"))
        self.assertIn("loop process", state["deaths"][0]["reason"])
        self.assertEqual(state["deaths"][0]["resumed_at"], self.now)
        self.assertTrue(any(
            line.startswith(f"resumed {directory.name}: loop died (") and
            "continuing executor of round 1" in line for line in self.logs))
        self.assertEqual(self.cards, [])
        word = watch.session_state(
            "seat", session={"name": "seat"}, records=[(directory, state)], live={},
            harness="claude", auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual(word["word"], "working")

    def test_launch_grace_and_an_ordered_resume_are_left_alone(self):
        grace = self.receipt("20260922-1301-grace", state="queued", launch_pending=True,
                             queued_at=self.now, process_identity=None)
        ordered = self.receipt("20260922-1301-ordered", stall_resume_at=self.now)
        watch.resume_dead_loops(dry_run=False, log=self.logs.append, now=self.now)
        self.assertEqual(self.resumed, [])
        self.assertEqual(run.read_state(grace)["state"], "queued")
        self.assertNotIn("deaths", run.read_state(ordered))
        self.assertEqual(self.cards, [])

    def died_again(self, directory, pid):
        """The resume ran and then died: the child had adopted the record, so the order
        stamp is gone and the pid on it is the one that has just exited."""
        state = run.read_state(directory)
        state.pop("stall_resume_at", None)
        state["pid"] = pid
        run.save_state(directory, state)

    def test_backoff_waits_and_a_third_death_parks_with_one_notice(self):
        directory = self.receipt("20260922-1302-backoff")
        self.tick()
        self.assertEqual(self.resumed, [directory.name])
        self.died_again(directory, 2 ** 30 - 1)
        self.tick(self.now + 60)
        self.assertEqual(self.resumed, [directory.name], "a second death inside 10 min waits")
        waiting = run.read_state(directory)
        self.assertEqual(len(waiting["deaths"]), 2)
        # The whole tick holds the wait, reap included: no interruption, no card, and the
        # seat goes on reading `working` for the ten minutes.
        self.assertEqual(waiting["state"], "running")
        self.assertNotIn("interrupted_at", waiting)
        self.assertFalse(waiting.get("recovery_pending"))
        self.assertEqual(self.cards, [])
        word = watch.session_state(
            "seat", session={"name": "seat"}, records=[(directory, waiting)], live={},
            harness="claude", auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual(word["word"], "working")
        self.assertTrue(any("next try after 10 min" in line for line in self.logs))
        self.tick(self.now + 700)
        self.assertEqual(len(self.resumed), 2, "the next try comes after the backoff")
        self.assertNotIn("resume_after", run.read_state(directory))
        self.died_again(directory, 2 ** 30 - 2)
        before = len(self.cards)
        self.tick(self.now + 760)
        parked = run.read_state(directory)
        self.assertEqual(parked["state"], "interrupted")
        self.assertTrue(parked["deaths"][-1]["parked"])
        self.assertEqual(len(self.resumed), 2, "a parked run is not launched")
        self.assertEqual(len(self.cards), before + 1)
        self.tick(self.now + 800)
        self.assertEqual(len(self.cards), before + 1, "the notice is once")

    def test_a_menu_look_before_the_tick_does_not_spend_the_recovery_card(self):
        directory = self.receipt("20260922-1302-look")
        run.reap(directory, run.read_state(directory))
        self.assertEqual(self.cards, [], "a death the tick answers is nobody's news")
        self.assertFalse(run.read_state(directory).get("recovery_notified"))
        # the reap records the death it noticed, which is how the next tick knows this
        # interruption is a loop to carry on and not one a person was handed
        self.assertEqual(len(run.read_state(directory)["deaths"]), 1)
        self.tick()
        state = run.read_state(directory)
        self.assertEqual(self.resumed, [directory.name])
        self.assertEqual(state["state"], "running")
        self.assertNotIn("interrupted_at", state)
        self.assertEqual(self.cards, [])

    def test_a_scope_the_memory_cap_ended_is_not_resumed(self):
        directory = self.receipt("20260922-1313-capped", memory_cap_mb=4096,
                                 scope="agentkit-test-cap-resume")
        # The manager is never asked here, and the scope named above is never started:
        # what this pins is that the pass asks at all, and leaves the `fail` reap
        # concludes to reap rather than carrying a leak on.
        with patch.object(run, "memory_cap_reason", return_value="killed: memory cap 4 GB"):
            watch.resume_dead_loops(dry_run=False, log=self.logs.append, now=self.now)
        self.assertEqual(self.resumed, [])
        self.assertNotIn("deaths", run.read_state(directory))
        self.assertEqual(self.cards, [])

    def test_stopped_run_and_a_missing_worktree_are_not_resumed(self):
        stopped = self.receipt("20260922-1303-stopped", state="stopped")
        missing = self.receipt("20260922-1303-gone", worktree=str(self.root / "no-such-tree"))
        # nothing to continue into, and an interruption nobody recorded a death on: both
        # stay a person's, exactly as they were before a tick resumed anything
        unstarted = self.receipt("20260922-1303-unstarted", worktree=None)
        older = self.receipt("20260922-1303-older", state="interrupted")
        watch.resume_dead_loops(dry_run=False, log=self.logs.append, now=self.now)
        self.assertEqual(self.resumed, [])
        self.assertEqual(run.read_state(stopped)["state"], "stopped")
        self.assertTrue(any("worktree" in line and "explicit resume" in line for line in self.logs))
        self.assertTrue(run.read_state(missing).get("dead_worktree_warned"))
        self.assertNotIn("deaths", run.read_state(unstarted))
        self.assertEqual(run.read_state(older)["state"], "interrupted")
        self.assertNotIn("deaths", run.read_state(older))
        self.assertEqual(self.cards, [])

    def test_executor_turn_resumes_its_session_into_the_next_attempt(self):
        directory = self.receipt("20260922-1304-executor")
        out = directory / "round-1" / "executor"
        out.mkdir(parents=True)
        (out / "session_id").write_text("sess-executor")
        lp = self.loop(directory.name)
        summary = run.execute(lp, "executor", "original task text", "executor")
        recorded = self.calls()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["sid"], "sess-executor")
        self.assertIn("Your process was ended by the host at", recorded[0]["prompt"])
        self.assertIn("do not start over.", recorded[0]["prompt"])
        self.assertEqual(recorded[0]["out"], "executor-attempt2")
        self.assertIn("continued", summary)
        self.assertTrue((directory / "round-1" / "executor-attempt2" / "final.md").is_file())
        self.assertFalse(run.read_state(directory)["resume_notice"]["restarted"])

    def test_a_resume_that_exits_with_no_output_starts_a_fresh_conversation(self):
        os.environ["RESUME_DIE"] = "dead-sid"
        directory = self.receipt("20260922-1305-dead-session", exec_session="dead-sid")
        out = directory / "round-1" / "executor"
        out.mkdir(parents=True)
        (out / "session_id").write_text("dead-sid")
        lp = self.loop(directory.name)
        run.execute(lp, "executor", "original task text", "executor")
        recorded = self.calls()
        self.assertEqual([call["sid"] for call in recorded], ["dead-sid", ""])
        self.assertEqual(run.read_state(directory)["exec_session"], "fresh-session")
        self.assertTrue(any(line == "resume of dead-sid failed; fresh conversation"
                            for line in self.logs))
        self.assertTrue(run.read_state(directory)["resume_notice"]["restarted"])
        self.assertIn("original task text", recorded[1]["prompt"])

    def test_reviewer_resume_counts_its_verdict_for_the_round(self):
        os.environ["RESUME_FINAL"] = "VERDICT: PASS\n## Findings\n- none\n"
        directory = self.receipt("20260922-1306-reviewer", step="reviewer", rounds=1)
        out = directory / "round-1" / "reviewer"
        out.mkdir(parents=True)
        (out / "session_id").write_text("sess-reviewer")
        (directory / "round-1" / "donewhen.log").write_text("$ true\n[exit 0]\n")
        (directory / "round-1" / "executor").mkdir()
        (directory / "round-1" / "executor" / "final.md").write_text("## Summary\ndone\n")
        lp = self.loop(directory.name)
        lp.rnd = 0
        run.rounds(lp)
        recorded = self.calls()
        self.assertTrue(recorded)
        self.assertTrue(all(call["prompt"].startswith("You are the reviewer") for call in recorded))
        self.assertEqual(recorded[0]["sid"], "sess-reviewer")
        self.assertIn("do not start over.", recorded[0]["prompt"])
        self.assertEqual(recorded[0]["out"], "reviewer-attempt2")
        state = run.read_state(directory)
        self.assertEqual(state["round_summaries"][-1]["verdict"], "PASS")
        self.assertEqual(state["verdict"], "PASS")

    def test_a_dead_fixer_session_starts_a_fresh_conversation(self):
        os.environ["RESUME_DIE"] = "sess-fixer"
        directory = self.receipt("20260922-1308-fixer", step="fixer")
        out = directory / "round-1" / "fixer"
        out.mkdir(parents=True)
        (out / "session_id").write_text("sess-fixer")
        lp = self.loop(directory.name)
        run.execute(lp, "fixer", "fix the done-when failure", "fixer")
        recorded = self.calls()
        self.assertEqual([call["sid"] for call in recorded], ["sess-fixer", ""])
        self.assertEqual(recorded[0]["out"], "fixer-attempt2")
        self.assertIn("fix the done-when failure", recorded[1]["prompt"])
        self.assertTrue(any(line == "resume of sess-fixer failed; fresh conversation"
                            for line in self.logs))
        self.assertTrue(run.read_state(directory)["resume_notice"]["restarted"])

    def test_a_dead_reviewer_session_judges_the_round_from_a_fresh_conversation(self):
        os.environ["RESUME_DIE"] = "sess-reviewer"
        os.environ["RESUME_FINAL"] = "VERDICT: PASS\n## Findings\n- none\n"
        directory = self.receipt("20260922-1309-dead-review", step="reviewer", rounds=1)
        out = directory / "round-1" / "reviewer"
        out.mkdir(parents=True)
        (out / "session_id").write_text("sess-reviewer")
        (directory / "round-1" / "donewhen.log").write_text("$ true\n[exit 0]\n")
        (directory / "round-1" / "executor").mkdir()
        (directory / "round-1" / "executor" / "final.md").write_text("## Summary\ndone\n")
        lp = self.loop(directory.name)
        lp.rnd = 0
        run.rounds(lp)
        recorded = self.calls()
        self.assertEqual([call["sid"] for call in recorded], ["sess-reviewer", ""])
        self.assertIn("do not start over.", recorded[0]["prompt"])
        self.assertIn("task body", recorded[1]["prompt"])
        self.assertNotIn("do not start over.", recorded[1]["prompt"])
        self.assertTrue(any(line == "resume of sess-reviewer failed; fresh conversation"
                            for line in self.logs))
        state = run.read_state(directory)
        self.assertEqual(state["round_summaries"][-1]["verdict"], "PASS")
        self.assertTrue(state["resume_notice"]["restarted"])

    def test_a_review_that_fell_back_is_continued_in_its_own_directory(self):
        os.environ["RESUME_FINAL"] = "VERDICT: PASS\n## Findings\n- none\n"
        directory = self.receipt("20260922-1310-fallback", step="reviewer", rounds=1)
        rd = directory / "round-1"
        (rd / "executor").mkdir(parents=True)
        (rd / "executor" / "final.md").write_text("## Summary\ndone\n")
        (rd / "donewhen.log").write_text("$ true\n[exit 0]\n")
        (rd / "reviewer").mkdir()
        # the first reviewer died without a verdict, so the round fell back to `astra`
        (rd / "reviewer" / "final.md").write_text("no verdict here\n")
        (rd / "reviewer-astra").mkdir()
        (rd / "reviewer-astra" / "session_id").write_text("sess-fallback")
        lp = self.loop(directory.name)
        lp.rnd = 0
        run.rounds(lp)
        recorded = self.calls()
        self.assertEqual(recorded[0]["sid"], "sess-fallback")
        self.assertEqual(recorded[0]["out"], "reviewer-astra-attempt2")
        self.assertIn("do not start over.", recorded[0]["prompt"])
        self.assertEqual(run.read_state(directory)["round_summaries"][-1]["verdict"], "PASS")

    def test_a_slot_wait_resumes_with_its_original_queued_at(self):
        waited_since = self.now - 3600
        directory = self.receipt("20260922-1311-slot", state="queued", slot_waiting=True,
                                 queued_at=waited_since, step=None)
        self.tick()
        state = run.read_state(directory)
        self.assertEqual(self.resumed, [directory.name])
        self.assertEqual(state["state"], "queued")
        self.assertEqual(state["queued_at"], waited_since, "it keeps its place in the queue")
        self.assertEqual(self.cards, [])
        clock = time.strftime("%H:%M", time.localtime(self.now))
        self.assertEqual(run.resume_age(state, self.now + 5),
                         f"resumed {clock} · continued the slot wait")

    def test_a_done_when_gate_cut_off_runs_again_without_another_executor_turn(self):
        os.environ["RESUME_FINAL"] = "VERDICT: PASS\n## Findings\n- none\n"
        directory = self.receipt("20260922-1312-donewhen", step="done-when", rounds=1)
        answer = directory / "round-1" / "executor"
        answer.mkdir(parents=True)
        (answer / "final.md").write_text("## Summary\ndone\n")
        self.assertEqual(run.continuation(self.loop(directory.name)), "done-when")
        self.assertIsNone(run.settled_gate(self.loop(directory.name)),
                          "a gate with no settled record runs again")
        lp = self.loop(directory.name)
        lp.rnd = 0
        gates = []
        # The gate's own commands are a real process tree, which no test here starts: what
        # a cut-off gate has to do is re-enter it rather than spend another executor turn.
        with patch.object(run, "verify_work", side_effect=lambda lp, cmds=None:
                          gates.append(lp.rnd) or (True, "$ true\n[exit 0]\n")):
            run.rounds(lp)
        self.assertEqual(gates, [1])
        self.assertEqual([call["out"] for call in self.calls()], ["reviewer"],
                         "the worker already answered; only the gate and the review are left")
        self.assertTrue(any("continuing done-when" in line for line in self.logs))

    def test_each_adapter_spells_the_resume_its_harness_takes(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        for harness in ("claude", "codex", "muse"):
            fake = binaries / harness
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >>"$ARGS"\nexit 0\n')
            fake.chmod(0o755)
        prompt = self.root / "prompt.md"
        prompt.write_text("continue this turn\n")
        for harness, spelling in (("claude", "-p --resume sess-1"),
                                  ("codex", "exec resume sess-1"),
                                  ("muse", "--session-id sess-1")):
            argv = self.root / f"{harness}.argv"
            subprocess.run(["bash", str(REPO / "adapters" / f"{harness}.sh"), "run", "model",
                            "low", str(self.root), str(prompt),
                            str(self.root / f"{harness}-out"), "sess-1"],
                           env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                                "ARGS": str(argv)}, check=False, timeout=120)
            self.assertIn(spelling, " ".join(argv.read_text().split()), harness)

    def test_status_shows_the_resumed_line_and_lists_deaths(self):
        directory = self.receipt("20260922-1307-status", **run.process_owner())
        state = run.read_state(directory)
        state["resume_notice"] = {"at": self.now, "role": "executor", "restarted": False}
        state["deaths"] = [{"at": self.now, "pid": 111,
                            "reason": "loop process 111 gone, noticed 2026-09-22 13:05:00"}]
        run.save_state(directory, state)
        out = io.StringIO()
        with patch.object(time, "time", return_value=self.now + 10), redirect_stdout(out):
            self.assertEqual(run.cmd_status([directory.name]), 0)
        text = out.getvalue()
        self.assertIn("resumed ", text)
        self.assertIn("continued the executor's turn", text)
        self.assertIn("loop process 111 gone", text)
        shown = io.StringIO()
        with patch.object(time, "time", return_value=self.now + 10), redirect_stdout(shown):
            self.assertEqual(run.main(["show", directory.name]), 0)
        self.assertIn("loop process 111 gone", shown.getvalue())
        # a gate is a step the loop continues, not a turn a model is in the middle of
        state["resume_notice"] = {"at": self.now, "role": "done-when", "restarted": False}
        self.assertTrue(run.resume_age(state, self.now + 10).endswith("continued the done-when"))


if __name__ == "__main__":
    unittest.main()

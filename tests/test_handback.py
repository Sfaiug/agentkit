"""v5ay: an ending goes back to the orchestrator that launched it, and a run that cannot
succeed says so early.

Offline.  The hand-back half fakes the seat (no tmux: `orch.sessions`/`listing` say what is
there, `watch.live_state` says what its screen shows) and the confirmed send, and drives the
real `run.announce` and the real `ak watch` tick.  The blocked half runs the real loop with
one fake harness per model in the catalogue, answering from a plan the test writes: no
network, no repository, no tmux.
"""

from contextlib import ExitStack, contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote_to_bytes

from test_v4n import REPO, Sandbox
from agentkit import browser, config, menu, notify, orch, run, terminal, watch

SEAT = "seat"
TYPE_CHECKED = watch.type_checked   # the real confirmed send, for the tests that drive it

# One fake harness for every model in the catalogue: it answers from a plan the test wrote,
# records the prompts it was given, and never leaves the fixture directory.
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["HANDBACK_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
if prompt.startswith("You are the reviewer"):
    role = "reviewer"
elif prompt.startswith("You are the executor, continuing"):
    role = "fixer"
else:
    role = "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role}) + "\\n")
plan = json.loads((root / "plan.json").read_text())
answers = plan.get(role) or ["## Summary\\nFixture work."]
answer = answers.pop(0) if len(answers) > 1 else answers[0]
plan[role] = answers
(root / "plan.json").write_text(json.dumps(plan))
pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
(out / "final.md").write_text(answer)
(out / "session_id").write_text("session-" + role)
'''

FAIL_REVIEW = "VERDICT: FAIL\n\n## Findings\n- file.py:1 - a pattern - why it matters\n"
BLOCKED_TURN = ("## Blocked\n\nThe done-when command checks a file the task never asks for, "
                "so no change can make it pass.\n")


class Claude:
    """A Claude Code seat as far as a typed line goes, under the real confirmed send.

    Text lands in the composer, and an Enter takes whatever is there: at the prompt it starts a
    turn, mid-turn it is queued, and the seat reads it either way.  What it took is echoed just
    above its composer, inside the bottom lines the send confirms against, and the screen still
    reads as a prompt: what the seat of run 20260923-2146 showed while its turn began.  `takes`
    off leaves every Enter's line in the composer; `fails` makes the next Enter's send fail;
    `dialog` puts the trust dialog over the composer, and an Enter then answers it.
    """

    def __init__(self):
        self.composer, self.read, self.typed, self.chosen = "", [], 0, 0
        self.takes, self.fails, self.dialog = True, False, False

    def keys(self, *args, socket=None, client=False):
        if args[0] == "send-keys" and args[-2] == "-l":
            self.composer += args[-1]
            self.typed += 1
        elif args[0] == "send-keys" and self.fails:
            self.fails = False
            return 1, "no server running"
        elif args[0] == "send-keys" and self.dialog:
            self.chosen += 1
        elif args[0] == "send-keys":
            self.enter()
        return 0, ""

    def enter(self):
        if self.composer and self.takes:
            self.read.append(self.composer)
            self.composer = ""

    def pane(self, *_args, **_kwargs):
        if self.dialog:
            return (REPO / "tests/fixtures/claude-dialog-pane.txt").read_text()
        return "".join(f"> {line}\n\n" for line in self.read) + f"\u276f {self.composer}\n"


class HandBack(Sandbox):
    """A finished run under a seat that is there, and under one that is gone."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": ""}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.rows = []              # what tmux holds, as the listing and a lookup report it
        self.screen = "at_prompt"   # what the classifier reads off that seat's pane
        self.pane = "\u276f\n"      # a capture for it to read; blank is no evidence at all
        self.rule = "prompt.composer"   # which rule matched it; `none` is nothing saying so
        self.sent = True            # what the fake confirmed send answers
        self.leaves = False         # the seat starts a turn between the two prompt checks
        self.logs, self.typed, self.cards, self.reopened = [], [], [], []
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        self.stack.enter_context(patch.object(orch, "listing", lambda *a, **k: list(self.rows)))
        self.stack.enter_context(patch.object(
            orch, "tmux_out", side_effect=AssertionError("tmux was called")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(
            watch, "live_state",
            side_effect=lambda *a, **k: {"state": self.screen, "rule": self.rule,
                                         "authority": "" if self.rule == "none" else "screen",
                                         "evidence": "", "began": 9000, "since": 9000}))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *a, **k: self.pane))
        self.stack.enter_context(patch.object(watch, "type_checked", side_effect=self.send))
        self.stack.enter_context(patch.object(
            watch, "type_into",
            side_effect=lambda session, text, log: self.typed.append(
                (session.get("name"), text)) or self.sent))
        self.stack.enter_context(patch.object(
            notify, "shaped",
            side_effect=lambda kind, text, **kw: self.cards.append((kind, text, kw)) or 0))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.stack.enter_context(patch.object(
            orch, "ensure",
            side_effect=lambda cfg, name, log=print, saved=False:
                self.reopened.append((name, saved)) or "resumed"))
        config.save_session(self.cfg, SEAT, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": "thread-seat", "id_source": orch.LAUNCHER})

    def send(self, session, text, log, harness=None, guard=nullcontext,
             veto=lambda _name: False, typed=lambda: None):
        """The confirmed send, minus tmux: the real lock is taken and the real veto read."""
        with guard() as held:
            if self.leaves:
                self.screen = "working"     # another run's ending got there first
            if veto(held if held is not None else session["name"]):
                return False
        typed()
        self.typed.append((session["name"], text))
        return self.sent

    def ended_review(self):
        """The successful review `Sandbox.ended` writes, for a record that adds to it."""
        return run.read_state(self.ended(".review-shape"))["review"]

    def live(self):
        return {"name": SEAT, "path": str(self.root), "created": 1, "attached": False,
                "exited": False, "legacy": False, "resumable": False}

    def failed(self, name="run-fail"):
        """A FAIL that spent its whole budget, with two findings still open."""
        return self.ended(name, owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                          round_summaries=[{}, {}, {}], findings=(
                              "VERDICT: FAIL\n\n## Findings\n- a.py:1 - one - why\n"
                              "- b.py:2 - two - why\n"))

    def tick(self):
        """One real `ak watch` pass, with GitHub unavailable so it stops before its PR passes."""
        with patch.object(watch, "health"), patch.object(watch, "recover_runs"), \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                patch.object(run, "schedule_gc"), patch.object(browser, "tidy"), \
                patch.object(notify, "tick_cards"), \
                patch.object(orch, "stamp"), patch.object(orch, "sweep"):
            self.assertEqual(watch.main([]), 0)

    # --- the hand-back ------------------------------------------------------

    def test_handback_is_typed_into_a_seat_that_is_at_its_prompt(self):
        directory = self.ended("run-1", owner=SEAT, merged=True,
                               pr="https://github.com/o/r/pull/7")
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [(SEAT, (
            "run run-1 finished PASS merged: https://github.com/o/r/pull/7. "
            f"Result: {directory / 'result.md'}. Decide the next step."))])
        self.assertEqual(self.cards, [])        # the owner is never the fallback
        self.assertEqual(self.reopened, [])     # nothing to reopen: somebody is in it
        state = run.read_state(directory)
        self.assertNotIn("handback_pending", state)
        self.assertTrue(state["reported"])

    def test_a_turn_in_flight_leaves_handback_pending_and_the_tick_delivers_it_once(self):
        directory = self.ended("run-2", owner=SEAT, no_merge=True)
        self.rows = [self.live()]
        self.screen = "working"
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards), ([], []))
        self.assertTrue(run.read_state(directory)["handback_pending"])
        # back at its prompt, the next tick types the line and clears the flag
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual(self.typed, [(SEAT, (
            "run run-2 finished PASS not merged: --no-merge. "
            f"Result: {directory / 'result.md'}. Decide the next step."))])
        self.assertNotIn("handback_pending", run.read_state(directory))
        # once: the tick that follows has nothing left to deliver
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.cards, [])

    def claude(self):
        """The real confirmed send into a fake Claude seat, whose screen reads as a prompt."""
        seat = Claude()
        self.stack.enter_context(patch.object(watch, "type_checked", TYPE_CHECKED))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=seat.keys))
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=seat.pane))
        return seat

    def test_a_line_the_seat_took_is_never_typed_again(self):
        # 2026-09-23, run 20260923-2146: the seat took the line and began its turn, the echo
        # above its composer read as the line still unsent, and the tick typed it again into
        # the turn in flight -- which queued it, and the seat read the ending twice.
        directory = self.ended("run-once", owner=SEAT, no_merge=True)
        self.rows = [self.live()]
        seat = self.claude()
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.tick()
        self.tick()
        self.assertEqual(seat.read, [
            "run run-once finished PASS not merged: --no-merge. "
            f"Result: {directory / 'result.md'}. Decide the next step."])
        state = run.read_state(directory)
        self.assertTrue(state["handed_back"])
        self.assertNotIn("handback_pending", state)
        self.assertEqual(self.cards, [])

    def test_a_jobs_line_the_seat_took_is_never_typed_again(self):
        job_dir = config.JOBS / "job-once"
        job_dir.mkdir(parents=True)
        line = "job job-once: 1 task(s) need you. Result: x. Decide the next step."
        run.save_job(job_dir, {"job_id": "job-once", "seat": SEAT, "tasks": [],
                               "finished_at": 9990, "handback_pending": line,
                               "handback_card": "job job-once: 1 task(s) need you"})
        self.rows = [self.live()]
        seat = self.claude()
        self.tick()
        self.tick()
        self.assertEqual(seat.read, [line])
        self.assertNotIn("handback_pending", run.read_job(job_dir))
        self.assertEqual(self.cards, [])

    def test_a_line_left_in_its_composer_gets_its_enter_and_never_a_second_copy(self):
        directory = self.ended("run-held", owner=SEAT, no_merge=True)
        self.rows = [self.live()]
        seat = self.claude()
        seat.takes = False          # both Enters leave it where it was typed
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(seat.read, [])
        self.assertTrue(run.read_state(directory)["handback_pending"])
        seat.takes = True
        lock = notify.session_lock

        @contextmanager
        def dialog_meanwhile(name):
            seat.dialog = True      # a dialog opens while the send lock is awaited
            with lock(name) as held:
                yield held

        with patch.object(notify, "session_lock", dialog_meanwhile):
            run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((seat.read, seat.chosen), ([], 0))
        seat.dialog = False
        self.tick()                 # the Enter it is owed, and not the text again
        # another ending is said before a pass reads that this one left its composer
        other = self.ended("run-other", owner=SEAT, no_merge=True)
        run.announce(run.read_state(other), other, self.logs.append)
        self.tick()                 # gone from the composer: the seat has it
        self.tick()
        self.assertEqual(seat.read, [
            f"run {name} finished PASS not merged: --no-merge. "
            f"Result: {path / 'result.md'}. Decide the next step."
            for name, path in (("run-held", directory), ("run-other", other))])
        self.assertEqual((seat.typed, seat.chosen), (2, 0))
        for path in (directory, other):
            state = run.read_state(path)
            self.assertTrue(state["handed_back"])
            self.assertNotIn("handback_pending", state)
            self.assertNotIn("handback_typed", state)

    def test_a_jobs_line_whose_enter_failed_is_never_typed_again(self):
        job_dir = config.JOBS / "job-enter"
        job_dir.mkdir(parents=True)
        line = "job job-enter: 1 task(s) need you. Result: x. Decide the next step."
        run.save_job(job_dir, {"job_id": "job-enter", "seat": SEAT, "tasks": [],
                               "finished_at": 9990, "handback_pending": line,
                               "handback_card": "job job-enter: 1 task(s) need you"})
        self.rows = [self.live()]
        seat = self.claude()
        seat.fails = True           # the text goes in and its Enter does not
        self.tick()
        self.assertEqual((seat.read, seat.composer), ([], line))
        self.assertEqual(run.read_job(job_dir)["handback_pending"], line)
        seat.enter()                # the owner sends it before the next pass
        self.tick()
        self.tick()
        self.assertEqual((seat.read, seat.typed), ([line], 1))
        self.assertNotIn("handback_pending", run.read_job(job_dir))
        self.assertEqual(self.cards, [])

    def test_a_fail_at_the_last_round_hands_back_and_sends_no_card(self):
        directory = self.failed()
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [(SEAT, (
            "run run-fail finished FAIL: after 3 rounds, open findings: "
            "- a.py:1 - one - why - b.py:2 - two - why. "
            f"Result: {directory / 'result.md'}. Decide the next step. "
            "three rounds spent: split or re-scope"))])
        self.assertEqual(self.cards, [])
        # and no row sends him to it either, while the seat that was told is still there
        found = watch.session_state(SEAT, session=self.live(), cfg=self.cfg)
        self.assertNotIn("run-fail", found["reason"])

    def test_a_fail_says_why_and_only_spent_reviews_say_split(self):
        # every review passed; the final check failed on the account, not on the work: the
        # line names the check's failing line, and no split is asked of a task nobody faulted
        scope = "`bash tests/smoke.sh` — FAIL  4 ak run: no delete_repo scope"
        checked = self.ended("run-40", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                             round_summaries=[{}, {}, {}],
                             findings="VERDICT: PASS\n\n## Findings\n- none\n",
                             final_check={"outcome": "failed", "sha": "a" * 40, "line": scope})
        line = run.handback_line(run.read_state(checked), checked)
        self.assertIn(f"finished FAIL: after 3 rounds, the final check failed: {scope}. Result:",
                      line)
        self.assertNotIn("split or re-scope", line)
        # a record from before the line was kept still names the check its gate recorded
        older = self.ended("run-41", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                           round_summaries=[{}, {}, {}], findings="VERDICT: PASS\n",
                           final_check={"outcome": "failed", "sha": "a" * 40},
                           done_when_failure={"every": [], "once": [
                               ["bash tests/smoke.sh", "acceptance: FAILED"]]})
        self.assertEqual(run.handback_reason(run.read_state(older)), "after 3 rounds, the final "
                         "check failed: `bash tests/smoke.sh` — acceptance: FAILED")
        # a review FAIL carries its blocking findings, the first 600 characters, and never
        # the follow-ups listed after them
        finding = "- a.py:1 - " + "x" * 700
        failed = self.ended("run-42", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                            round_summaries=[{}, {}, {}], findings=(
                                f"VERDICT: FAIL\n\n## Findings\n{finding}\n\n"
                                "## Follow-ups\n- c.py:3 - rename it - clarity\n"))
        state = run.read_state(failed)
        self.assertEqual(run.handback_reason(state),
                         f"after 3 rounds, open findings: {finding[:600]}")
        self.assertTrue(run.handback_line(state, failed).endswith(
            "three rounds spent: split or re-scope"))

    def test_a_long_review_and_an_overridden_pass_still_say_why(self):
        # run.json keeps a review's last 8000 characters, and a long one's verdict and first
        # findings are at its top: the line reads the whole answer the round left on disk
        first = "- a.py:1 - the gate is off by one - wrong outcome"
        whole = (f"VERDICT: FAIL\n\n## Findings\n{first}\n"
                 + "".join(f"- n{i}.py:1 - {'y' * 80}\n" for i in range(150)))
        self.assertGreater(len(whole), 12000)
        answer = self.root / "final.md"
        answer.write_text(whole)
        long = self.ended("run-43", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                          round_summaries=[{}, {}, {}], findings=whole.strip()[-8000:],
                          findings_file=str(answer))
        state = run.read_state(long)
        self.assertTrue(run.handback_reason(state).startswith(
            f"after 3 rounds, open findings: {first} - n0.py:1 - "))
        self.assertTrue(run.handback_line(state, long).endswith(
            "three rounds spent: split or re-scope"))
        # a PASS the loop failed -- the reviewer exited 1, the checkout moved -- says so
        review = {**self.ended_review(), "verdict": "FAIL", "returncode": 1,
                  "overridden": "the reviewer said PASS but exited 1"}
        exited = self.ended("run-44", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                            round_summaries=[{}, {}, {}], review=review,
                            findings="VERDICT: PASS\n\n## Findings\n- none\n")
        line = run.handback_line(run.read_state(exited), exited)
        self.assertIn("finished FAIL: after 3 rounds, the reviewer said PASS but exited 1. "
                      "Result:", line)
        self.assertNotIn("split or re-scope", line)

    def test_a_gone_seat_keeps_the_orphan_path_it_always_had(self):
        directory = self.ended("run-3", owner=SEAT, handback_pending=True)
        self.rows = []                       # nobody is in it and tmux holds nothing
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(self.typed, [(SEAT, "continue Finished run-3: run run-3 finished "
                                             f"PASS, result at {directory / 'result.md'}")])
        self.assertEqual(self.cards, [])
        state = run.read_state(directory)
        self.assertTrue(state["reported"])
        self.assertNotIn("handback_pending", state)
        # ... and when the seat cannot be reopened at all, the owner is asked as before
        gone = self.ended("run-4", owner=SEAT, state="fail", verdict="FAIL")
        with patch.object(watch, "seat_closed", return_value=True):
            run.announce(run.read_state(gone), gone, self.logs.append)
        self.assertEqual([kind for kind, _, _ in self.cards], ["needs"])
        self.assertIn(f"Its orchestrator session {SEAT} is gone.", self.cards[0][1])

    def test_an_ending_under_a_gone_seat_is_handed_back_not_rowed(self):
        self.failed("run-5")
        self.rows = [{**self.live(), "exited": True}]
        found = watch.session_state(SEAT, session=self.rows[0], cfg=self.cfg, number=1)
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "session closed: press 1 to reopen")

    def test_an_ending_already_handed_back_stays_the_orchestrators_when_the_seat_closes(self):
        directory = self.failed("run-8")
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertTrue(run.read_state(directory)["handed_back"])
        # the seat closes afterwards: the ending was said, so no row sends the owner to it
        self.rows = [{**self.live(), "exited": True}]
        found = watch.session_state(SEAT, session=self.rows[0], cfg=self.cfg, number=1)
        self.assertEqual(found["reason"], "session closed: press 1 to reopen")
        # and the tick leaves it alone however it is flagged
        run.save_state(directory, {**run.read_state(directory), "notification_pending": True})
        self.rows = [self.live()]
        self.tick()
        self.assertEqual(len(self.typed), 1)

    def test_an_orphan_notice_the_seat_came_back_from_is_not_sent_twice(self):
        directory = self.failed("run-9")
        self.rows = []              # it died, the continue line never landed, and the card
        self.sent = False           # the owner was offered was not accepted either
        with patch.object(notify, "shaped", return_value=1):
            run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertTrue(run.read_state(directory)["notification_pending"])
        # it comes back: one hand-back, and nothing pending for any later tick to repeat
        self.rows = [self.live()]
        self.sent = True
        self.typed.clear()
        self.tick()
        self.tick()
        self.assertEqual(len(self.typed), 1)
        state = run.read_state(directory)
        self.assertNotIn("notification_pending", state)
        self.assertNotIn("handback_pending", state)

    def test_a_resumed_ending_hands_back_instead_of_asking_for_recovery(self):
        # a resume leaves `recovery_pending` on the record; the attempt still ended, so the
        # line is a verdict's and not a recovery notice's, and nothing says it twice
        directory = self.ended("run-10", owner=SEAT, state="fail", verdict="FAIL",
                               recovery_pending=True, rounds=2, round_summaries=[{}, {}],
                               findings="VERDICT: FAIL\n\n## Findings\n- a.py:1 - one - why\n")
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [(SEAT, (
            "run run-10 finished FAIL: after 2 rounds, open findings: - a.py:1 - one - why. "
            f"Result: {directory / 'result.md'}. Decide the next step. "
            "two rounds spent: split or re-scope"))])
        self.assertEqual(self.cards, [])
        # reaping it afterwards is not a second chance to say the same thing
        run.reap(directory, run.read_state(directory))
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.cards, [])

    def test_a_new_attempt_forgets_what_the_last_ending_said(self):
        directory = self.failed("run-18")
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertTrue(run.read_state(directory)["handed_back"])
        run.save_state(directory, {**run.read_state(directory), "state": "interrupted",
                                   "recovery_pending": True, "finished_at": None,
                                   "scratch": True, "worktree": str(self.root), "rounds": 3})
        (directory / "task.md").write_text(
            "---\nrepo: none\n---\n# T\n\n## Done when\n```bash\ntrue\n```\n")
        with patch.object(run, "drive", return_value=0), patch.object(run, "logger",
                                                                      return_value=print):
            run.cmd_resume([directory.name])
        state = run.read_state(directory)
        self.assertNotIn("handed_back", state)
        self.assertNotIn("handback_pending", state)
        # and a mark that outlived an attempt anyway cannot outlive the next pending ending:
        # this attempt ended long after that line was typed, so nobody has heard this one
        run.save_state(directory, {**run.read_state(directory), "state": "fail",
                                   "verdict": "FAIL", "finished_at": 9995, "handed_back": 1})
        self.screen = "working"
        run.announce(run.read_state(directory), directory, self.logs.append)
        state = run.read_state(directory)
        self.assertTrue(state["handback_pending"])
        self.assertNotIn("handed_back", state)
        self.screen = "at_prompt"
        self.typed.clear()
        self.tick()
        self.assertEqual(len(self.typed), 1)

    def test_an_interrupted_run_hands_back_a_result_that_exists(self):
        directory = self.ended("run-19", owner=SEAT, state="interrupted", verdict=None,
                               finished_at=None, interrupted_at=9990, recovery_pending=True,
                               interruption_reason="Run process exited or its identity changed.",
                               rounds=2, round_summaries=[], findings="")
        (directory / "result.md").unlink(missing_ok=True)
        self.rows = [self.live()]
        run.notify_recovery(directory, run.read_state(directory))
        self.assertEqual(self.typed, [(SEAT, (
            "run run-19 finished FAIL: Run process exited or its identity changed. "
            f"Result: {directory / 'result.md'}. Decide the next step."))])
        self.assertTrue((directory / "result.md").is_file())

    def test_a_gone_seat_is_revived_before_the_owner_is_asked_about_an_interruption(self):
        directory = self.ended("run-20", owner=SEAT, state="interrupted", verdict=None,
                               finished_at=None, interrupted_at=9990, recovery_pending=True,
                               rounds=2, round_summaries=[], findings="")
        self.rows = []                      # nobody is in it any more
        run.notify_recovery(directory, run.read_state(directory))
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(len(self.typed), 1)
        self.assertIn("is unfinished:", self.typed[0][1])
        self.assertEqual(self.cards, [])
        self.assertEqual(run.read_state(directory)["recovery_notified"], "orchestrator")
        # ... and the owner is asked only when there is no seat to bring back
        other = self.ended("run-21", owner=SEAT, state="interrupted", verdict=None,
                           finished_at=None, interrupted_at=9991, recovery_pending=True,
                           rounds=2, round_summaries=[], findings="")
        with patch.object(watch, "seat_closed", return_value=True):
            run.notify_recovery(other, run.read_state(other))
        self.assertEqual([kind for kind, _, _ in self.cards], ["needs"])

    def test_a_task_inside_a_job_still_hands_its_own_ending_back(self):
        directory = self.failed("run-22")
        self.rows = [self.live()]
        with run.job_muted():
            run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.cards, [])
        # its orphan, though, is the job's card and never a per-task one
        gone = self.failed("run-23")
        self.rows = []
        with run.job_muted():
            run.announce(run.read_state(gone), gone, self.logs.append)
        self.assertEqual((len(self.typed), self.cards), (1, []))

    def test_an_ending_the_orchestrator_has_is_in_no_tally_of_his(self):
        directory = self.failed("run-26")
        states = [run.read_state(directory)]
        # untouched, it is his: one ending needing him on the seat's own bar
        self.assertEqual(run.seat_tallies(states, now=9995)[SEAT], (0, 1, 0))
        self.assertTrue(menu.v5o_needs_look(states[0], now=9995))
        # waiting for the seat's next quiet prompt, and once it has been told: neither
        for mark in ({"handback_pending": True}, {"handed_back": 9991}):
            with self.subTest(mark=mark):
                run.save_state(directory, {**run.read_state(directory), **mark})
                state = run.read_state(directory)
                self.assertFalse(menu.v5o_needs_look(state, now=9995))
                self.assertEqual(run.seat_tallies([state], now=9995)[SEAT], (0, 0, 0))
                run.save_state(directory, {k: v for k, v in state.items() if k not in mark})

    def test_the_owner_glancing_at_a_run_is_not_the_orchestrator_hearing_it(self):
        # `r` and `ak run status <id>` mark an ending looked at, which settles it for him --
        # but he is never the fallback, so it cannot be what the seat was owed
        directory = self.failed("run-27")
        self.rows = [self.live()]
        self.screen = "working"
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertTrue(run.read_state(directory)["handback_pending"])
        with redirect_stdout(io.StringIO()):
            run.cmd_status([directory.name])
        self.assertTrue(run.read_state(directory)["recovery_acknowledged_at"])
        self.assertTrue(run.owes_ending(run.read_state(directory)))
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertIn("finished FAIL:", self.typed[0][1])

    def test_two_snapshots_of_one_ending_deliver_it_exactly_once(self):
        # the loop that finished the run and the tick that found it unheard both hold a copy:
        # whoever takes the delivery lock second reads the record, not its own snapshot
        directory = self.failed("run-28")
        self.rows = [self.live()]
        loops, ticks = run.read_state(directory), run.read_state(directory)
        run.announce(loops, directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        run.announce(ticks, directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        state = run.read_state(directory)
        self.assertTrue(state["handed_back"])       # the stale snapshot did not erase it
        self.assertTrue(state["reported"])
        self.assertNotIn("handback_pending", state)
        # ... and no later quiet prompt gets a second line
        self.tick()
        self.assertEqual(len(self.typed), 1)

    def test_a_job_task_under_a_gone_seat_stays_the_jobs_to_report(self):
        directory = self.failed("run-29")
        self.rows = []
        with run.job_muted():
            run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))
        # the tick runs in another process with no mute of its own: the record has to say
        # the ending went somewhere, or every pass would revive the seat or card the owner
        self.assertFalse(run.owes_ending(run.read_state(directory)))
        self.tick()
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))

    def test_two_ticks_over_one_pending_job_type_its_line_once(self):
        job_dir = config.JOBS / "job-2"
        job_dir.mkdir(parents=True)
        line = "job job-2: 1 task(s) need you. Result: x. Decide the next step."
        run.save_job(job_dir, {"job_id": "job-2", "seat": SEAT, "tasks": [{"name": "a",
                               "state": "failed"}], "finished_at": 9990,
                               "handback_pending": line, "handback_card": "job job-2: needs you"})
        self.rows = [self.live()]
        # two overlapping passes, each with its own copy of the record
        first, second = run.read_job(job_dir), run.read_job(job_dir)
        self.assertEqual(run.job_hand_back(SEAT, first["handback_pending"],
                                           self.logs.append), "sent")
        run.mark_job_delivery(job_dir, first, handback_pending=None, handback_card=None,
                              card_sent={"kind": "handback", "at": 9990})
        run.deliver_job_handbacks(self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.cards, [])
        saved = run.read_job(job_dir)
        self.assertNotIn("handback_pending", saved)
        self.assertEqual(saved["card_sent"]["kind"], "handback")
        # and the stale copy cannot put the job's tasks back as they were
        run.mark_job_delivery(job_dir, second, card_pending=True)
        self.assertEqual(run.read_job(job_dir)["card_sent"]["kind"], "handback")

    def test_a_stale_snapshot_cannot_mark_the_attempt_that_replaced_it(self):
        # what a tick or a draw is holding when a resume starts under it: the ending it is
        # about is nobody's business any more, and the attempt running now owes its own
        directory = self.failed("run-33")
        stale = run.read_state(directory)
        run.save_state(directory, {**run.clear_delivery(run.read_state(directory)),
                                   "state": "running", "finished_at": None, "pid": 4242})
        self.assertFalse(run.same_attempt(stale, run.read_state(directory)))
        running = run.read_state(directory)
        for marks in ({"reported": True}, {"handed_back": 9991},
                      {"handback_pending": True}, {"pending_inbox": None}):
            with self.subTest(marks=marks):
                self.assertFalse(run.mark_delivery(directory, dict(stale), **marks))
                self.assertEqual(run.read_state(directory), running)
        # the new attempt ends, and its own ending is handed back as any other
        run.save_state(directory, {**run.read_state(directory), "state": "fail",
                                   "verdict": "FAIL", "finished_at": 9995})
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertTrue(run.read_state(directory)["handed_back"])

    def test_a_stale_snapshot_never_types_a_replaced_attempts_line(self):
        directory = self.failed("run-34")
        stale = run.read_state(directory)
        run.save_state(directory, {**run.clear_delivery(run.read_state(directory)),
                                   "state": "running", "finished_at": None, "pid": 4242})
        self.rows = [self.live()]
        self.assertFalse(run.hand_back(stale, directory, self.logs.append))
        self.assertEqual(self.typed, [])
        self.assertNotIn("handback_pending", run.read_state(directory))
        self.assertIn(f"run {directory.name} has moved on since this ending", self.logs[-1])

    def test_a_stale_snapshot_cannot_clear_a_resumed_jobs_pending_line(self):
        job_dir = config.JOBS / "job-3"
        job_dir.mkdir(parents=True)
        line = "job job-3: 1 task(s) need you. Result: x. Decide the next step."
        run.save_job(job_dir, {"job_id": "job-3", "seat": SEAT, "tasks": [], "pid": 11,
                               "finished_at": 9990, "handback_pending": line})
        stale = run.read_job(job_dir)
        run.save_job(job_dir, {**run.read_job(job_dir), "pid": 22, "finished_at": 9995})
        self.assertFalse(run.mark_job_delivery(job_dir, stale, handback_pending=None))
        self.assertEqual(run.read_job(job_dir)["handback_pending"], line)

    def test_the_inbox_question_going_out_cannot_undo_a_hand_back(self):
        # the tick defers the line because the seat is mid-turn, then posts the run's merge
        # question -- and the run's own loop hands the ending back while that is in flight
        directory = self.failed("run-31")
        run.save_state(directory, {**run.read_state(directory), "pending_inbox": {
            "question": "Merge PR #9?", "url": "https://github.com/o/r/pull/9", "sha": "abc"}})
        self.rows = [self.live()]
        self.screen = "working"

        def deliver(kind, text, **kw):
            """The loop gets there while the question is going out."""
            self.cards.append((kind, text, kw))
            if kind == "needs" and "Merge PR" in text:
                self.screen = "at_prompt"
                run.announce(run.read_state(directory), directory, self.logs.append)
            return 0

        with patch.object(notify, "shaped", side_effect=deliver):
            self.tick()
        state = run.read_state(directory)
        self.assertTrue(state["handed_back"])       # the tick's own copy did not undo it
        self.assertNotIn("handback_pending", state)
        self.assertNotIn("pending_inbox", state)    # ... and the question is still struck off
        self.assertEqual(len(self.typed), 1)
        # no later tick says it a second time
        self.tick()
        self.assertEqual(len(self.typed), 1)

    def test_the_runs_list_marking_an_ending_seen_cannot_undo_a_hand_back(self):
        directory = self.failed("run-32")
        stale = run.read_state(directory)            # what a draw minutes ago is holding
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        run.mark_delivery(directory, stale, reported=True)
        self.assertTrue(run.read_state(directory)["handed_back"])
        self.assertFalse(run.owes_ending(run.read_state(directory)))

    def test_an_ending_no_flag_marks_is_still_offered_by_the_tick(self):
        # a resumed attempt that ended carries no pending flag at all: `reap` leaves an
        # ending to `announce`, and nothing else was going to say it
        directory = self.ended("run-24", owner=SEAT, state="fail", verdict="FAIL",
                               recovery_pending=True, rounds=2, round_summaries=[{}, {}],
                               findings="VERDICT: FAIL\n\n## Findings\n- a.py:1 - one - why\n")
        self.assertTrue(run.owes_ending(run.read_state(directory)))
        self.rows = [self.live()]
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertIn("finished FAIL: after 2 rounds, open findings: - a.py:1 - one - why",
                      self.typed[0][1])
        # said once: the next tick finds it heard
        self.assertFalse(run.owes_ending(run.read_state(directory)))
        self.tick()
        self.assertEqual(len(self.typed), 1)

    def test_a_resume_forgets_that_an_earlier_attempt_was_notified(self):
        state = {"state": "interrupted", "reported": True, "handed_back": 1,
                 "handback_pending": True, "notification_pending": True,
                 "recovery_notified": "needs"}
        run.clear_delivery(state)
        self.assertEqual(state, {"state": "interrupted", "reported": False})
        # so the next interruption of the same run is handed back rather than kept quiet
        directory = self.ended("run-25", owner=SEAT, state="interrupted", verdict=None,
                               finished_at=None, interrupted_at=9990, recovery_pending=True,
                               recovery_notified="needs", rounds=2, round_summaries=[],
                               findings="")
        self.rows = [self.live()]
        run.notify_recovery(directory, run.read_state(directory))
        self.assertEqual(self.typed, [])            # the stale mark keeps it quiet
        run.save_state(directory, run.clear_delivery(run.read_state(directory)))
        run.notify_recovery(directory, run.read_state(directory))
        self.assertEqual(len(self.typed), 1)

    def test_nothing_is_collected_while_it_still_owes_its_seat_a_line(self):
        directory = self.ended("20260101-0101-merged-run", owner=SEAT, merged=True,
                               finished_at=1, started_at=0, worktree=str(self.root / "gone"),
                               repo=str(self.root / "repo"), handback_pending=True)
        plans = [item for item in run.gc_plan(now=9_000_000) if item.get("run") == str(directory)]
        self.assertEqual(plans, [])
        run.save_state(directory, {k: v for k, v in run.read_state(directory).items()
                                   if k != "handback_pending"})
        job_dir = config.JOBS / "job-gc"
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, {"job_id": "job-gc", "seat": SEAT, "finished_at": 1,
                               "tasks": [{"name": "a", "state": "failed"}],
                               "handback_pending": "job job-gc: 1 task(s) need you"})
        self.assertEqual([item for item in run.gc_plan(now=9_000_000)
                          if item.get("job") == str(job_dir)], [])
        run.save_job(job_dir, {k: v for k, v in run.read_job(job_dir).items()
                               if k != "handback_pending"})
        self.assertTrue([item for item in run.gc_plan(now=9_000_000)
                         if item.get("job") == str(job_dir)])

    def test_a_delivery_retry_that_ends_blocked_is_recorded_as_blocked(self):
        # `ak run merge` runs fixer turns of its own; when one of them says the task is
        # wrong, the receipt keeps that word rather than calling it a failed delivery
        directory = self.failed("run-30")
        run.save_state(directory, {**run.read_state(directory), "state": "blocked",
                                   "verdict": "BLOCKED", "error": run.BLOCKED_SAME})
        state = run.read_state(directory)
        task = {"name": "a.md", "state": "running", "run_id": directory.name}
        job = {"job_id": "j", "seat": SEAT, "tasks": [task]}
        job_dir = config.JOBS / "j"
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, job)
        import threading
        with patch.object(run, "cmd_merge", return_value=1), \
                patch.object(run, "read_state", return_value=state):
            run.job_ladder(self.cfg, job_dir, job, task,
                           directory, {**state, "state": "pass", "merge_failed": True},
                           1, self.logs.append, threading.Lock())
        self.assertEqual(task["state"], "blocked")
        self.assertEqual(task["verdict_line"], f"a.md: BLOCKED: {run.BLOCKED_SAME}")
        self.assertIn("blocked", run.JOB_UNDELIVERED)

    def test_a_blocked_task_is_a_terminal_job_state_of_its_own(self):
        self.assertIn("blocked", run.JOB_TERMINAL)
        self.assertIn("blocked", run.JOB_UNDELIVERED)
        self.assertEqual(run.job_classify({"state": "blocked"}, self.cfg), "blocked")
        task = {"name": "a.md", "state": "blocked"}
        self.assertEqual(run.job_verdict_line(task, {"error": run.BLOCKED_SAME}),
                         f"a.md: BLOCKED: {run.BLOCKED_SAME}")
        job = {"job_id": "j", "tasks": [task, {"name": "b.md", "state": "merged"}]}
        self.assertEqual(run.job_block_line(job), "job j: 1 merged, 1 blocked")

    def test_a_job_task_its_reviews_failed_at_the_budget_goes_back_with_no_more_rounds(self):
        # three rounds is the budget inside a job too: the task's run hands its findings to
        # the seat the way a single run does, and the ladder neither resumes it with more
        # rounds nor reruns it on another model
        directory = self.failed("run-45")
        run.save_state(directory, {**run.read_state(directory), "worktree": str(self.root)})
        state = run.read_state(directory)
        self.assertTrue(run.failed_at_budget(state))
        self.rows = [self.live()]
        with run.job_muted():
            run.announce(state, directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertIn("finished FAIL: after 3 rounds, open findings: - a.py:1 - one - why",
                      self.typed[0][1])
        self.assertTrue(self.typed[0][1].endswith("three rounds spent: split or re-scope"))
        task = {"name": "a.md", "state": "running", "run_id": directory.name}
        job = {"job_id": "j", "seat": SEAT, "tasks": [task], "opts": {}}
        job_dir = config.JOBS / "j"
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, job)
        import threading
        with patch.object(run, "cmd_resume", side_effect=AssertionError("given more rounds")), \
                patch.object(run, "job_start_task", side_effect=AssertionError("rerun")):
            run.job_ladder(self.cfg, job_dir, job, task, directory, state, 1,
                           self.logs.append, threading.Lock())
        self.assertEqual(task["state"], "failed")
        self.assertEqual(task["verdict_line"], "a.md: FAIL after 3 rounds: needs you")
        self.assertIn("- a.py:1 - one - why", task["findings"])
        self.assertEqual(run.read_job(job_dir)["tasks"][0]["state"], "failed")
        # ... and the job's own ending gives the seat those findings, never the owner
        with patch.object(orch, "stop_scope"):
            self.assertEqual(run.run_job_loop(self.cfg, job_dir, run.read_job(job_dir)), 1)
        self.assertEqual(len(self.typed), 2)
        self.assertIn("- a.py:1 - one - why", self.typed[1][1])
        self.assertTrue(self.typed[1][1].endswith("Decide the next step."))
        self.assertEqual(self.cards, [])
        # a FAIL at the budget its reviews passed -- a check left it behind -- keeps its one
        # rerun on the next executor model, and still no added round
        checked = self.ended("run-46", owner=SEAT, state="fail", verdict="FAIL", rounds=3,
                             round_summaries=[{}, {}, {}], worktree=str(self.root),
                             findings="VERDICT: PASS\n\n## Findings\n- none\n")
        task = {"name": "b.md", "state": "running", "run_id": checked.name}
        with patch.object(run, "cmd_resume", side_effect=AssertionError("given more rounds")), \
                patch.object(run, "job_start_task",
                             side_effect=config.Error("fixture stop")) as start:
            run.job_ladder(self.cfg, job_dir, {**job, "tasks": [task]}, task, checked,
                           run.read_state(checked), 1, self.logs.append, threading.Lock())
        start.assert_called_once()
        self.assertTrue(task["rerun_attempted"])
        self.assertEqual(task["state"], "failed")

    def test_each_gate_keeps_its_own_failure_history(self):
        class Fake:
            state = None

            def save(self):
                pass

        once = "$ bash tests/smoke.sh\n[exit 1]\nE nope"
        lp = Fake()
        lp.state = {}
        run.same_failure(lp, False, once, gate="once")
        run.same_failure(lp, True, "$ pytest\n[exit 0]\nfine")   # an ordinary round passing
        self.assertEqual(lp.state["done_when_failure"]["once"],   # ... says nothing about it
                         [["bash tests/smoke.sh", "E nope"]])
        with self.assertRaises(run.Blocked):
            run.same_failure(lp, False, once, gate="once")
        # a round resumed from another process records without judging: nothing here knows
        # whether a fixer preceded it, but the round after it has to be able to compare
        lp.state = {}
        run.same_failure(lp, False, once, gate="once", compare=False)
        run.same_failure(lp, False, once, gate="once", compare=False)
        with self.assertRaises(run.Blocked):
            run.same_failure(lp, False, once, gate="once")

    def test_the_merge_pipeline_never_writes_the_rounds_own_failure_history(self):
        """A merge-pipeline gate has nothing to be the same as, and must overwrite nothing.

        The per-round commands passed before the merge began -- that is how the run got
        here -- so the gate after a conflict or final-check fixer has no previous failure of
        its own to compare with, and the rounds' history is the rounds' to write.
        """
        from types import SimpleNamespace
        directory = config.RUNS / "pipeline-probe"
        directory.mkdir(exist_ok=True)
        rounds_said = {"every": [["pytest", "E one != two"]]}
        fixers = []
        lp = SimpleNamespace(
            state={"round_summaries": [], "rounds": 3, "final_check": None,
                   "done_when_failure": dict(rounds_said)},
            rounds=3, rnd=1, once=["bash tests/smoke.sh"], every=["pytest"],
            wt=str(self.root), run_dir=directory, artifacts=set(), done_when_limit=1,
            turn_limit=1, context="ctx", executor="opus", log=self.logs.append,
            save=lambda: None)
        with patch.object(run, "git", return_value="a" * 40), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "commit_identity",
                             return_value={"head_sha": "a" * 40, "tree_sha": "b" * 40}), \
                patch.object(run, "run_done_when",
                             return_value=(False, "$ bash tests/smoke.sh\n[exit 1]\nE no")), \
                patch.object(run, "target_fails", return_value=False), \
                patch.object(run, "save_state"), patch.object(run, "note", return_value=False), \
                patch.object(run, "execute",
                             side_effect=lambda *a, **k: fixers.append(1) or "## Summary\nfix"), \
                patch.object(run, "verify_work", return_value=(True, "$ pytest\n[exit 0]")), \
                patch.object(run, "review", return_value="PASS"), \
                patch.object(run, "integrate", return_value=True):
            with self.assertRaises(run.Blocked):
                run.final_check(lp, "origin/main")
        self.assertEqual(len(fixers), 1)
        # the once-gate was judged, and the rounds' history is exactly as it was left
        self.assertEqual(lp.state["done_when_failure"]["every"], rounds_said["every"])

    def test_a_resumed_final_check_gives_a_fixer_a_turn_before_it_judges(self):
        """`final_check` walks back in on the signature its last attempt left behind.

        Nothing has been asked to fix anything since it was written down, so the first check
        of this attempt only records; the one after the fixer is the one that judges.
        """
        from types import SimpleNamespace
        directory = config.RUNS / "final-check-probe"
        directory.mkdir(exist_ok=True)
        failure = "$ bash tests/smoke.sh\n[exit 1]\nE the suite says no"
        fixers = []
        lp = SimpleNamespace(
            state={"round_summaries": [], "rounds": 3, "final_check": None,
                   "done_when_failure": {"once": [["bash tests/smoke.sh",
                                                  "E the suite says no"]]}},
            rounds=3, rnd=1, once=["bash tests/smoke.sh"], every=["true"],
            wt=str(self.root), run_dir=directory, artifacts=set(), done_when_limit=1,
            turn_limit=1, context="ctx", executor="opus", log=self.logs.append,
            save=lambda: None)
        with patch.object(run, "git", return_value="a" * 40), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "commit_identity",
                             return_value={"head_sha": "a" * 40, "tree_sha": "b" * 40}), \
                patch.object(run, "run_done_when", return_value=(False, failure)), \
                patch.object(run, "target_fails", return_value=False), \
                patch.object(run, "save_state"), patch.object(run, "note", return_value=False), \
                patch.object(run, "execute",
                             side_effect=lambda *a, **k: fixers.append(1) or "## Summary\nfix"), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")), \
                patch.object(run, "review", return_value="PASS"), \
                patch.object(run, "integrate", return_value=True):
            with self.assertRaises(run.Blocked) as blocked:
                run.final_check(lp, "origin/main")
        self.assertEqual(len(fixers), 1)
        # the BLOCKED line names what kept failing, not only that something did
        self.assertEqual(str(blocked.exception), f"{run.BLOCKED_SAME}; the final check still "
                         "fails on `bash tests/smoke.sh` — E the suite says no")

    def test_a_stop_no_window_will_lift_hands_back_and_a_quota_one_stays_quiet(self):
        self.rows = [self.live()]
        quota = self.ended("run-11", owner=SEAT, state="exhausted", quota_dry=True,
                           finished_at=None, error="every provider is spent")
        run.notify_recovery(quota, run.read_state(quota))
        self.assertEqual((self.typed, self.cards), ([], []))
        # nothing resumes a stop that is not a window: the seat hears it like any ending
        stuck = self.ended("run-12", owner=SEAT, state="exhausted", finished_at=None,
                           error="the reviewer gave no verdict twice")
        run.notify_recovery(stuck, run.read_state(stuck))
        self.assertEqual(self.typed, [(SEAT, (
            "run run-12 finished FAIL: the reviewer gave no verdict twice. "
            f"Result: {stuck / 'result.md'}. Decide the next step."))])
        self.assertEqual(self.cards, [])
        self.assertEqual(run.read_state(stuck)["recovery_notified"], "orchestrator")

    def test_a_seat_with_no_readable_screen_is_never_typed_into(self):
        directory = self.failed("run-13")
        self.rows = [self.live()]
        self.pane = "   \n"                   # a failed capture reads as nothing at all
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards), ([], []))
        self.assertTrue(run.read_state(directory)["handback_pending"])

    def test_a_screen_nothing_recognised_is_not_a_prompt_on_any_harness(self):
        # claude's word is its hooks': with no hook fact and no rule that matched, `classify`
        # offers `at_prompt` because it has nothing to go on, which is not evidence of one
        directory = self.failed("run-17")
        self.rows = [self.live()]
        self.rule = "none"
        self.assertFalse(watch.at_prompt(self.live(), cfg=self.cfg))
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards), ([], []))
        self.assertTrue(run.read_state(directory)["handback_pending"])

    def test_a_seat_that_leaves_its_prompt_under_the_lock_is_not_typed_into(self):
        directory = self.failed("run-14")
        self.rows = [self.live()]
        self.leaves = True                    # another ending got there first
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards), ([], []))
        self.assertTrue(run.read_state(directory)["handback_pending"])

    def test_the_seat_is_typed_into_in_the_world_the_lookup_found_it_in(self):
        # a suite running inside a seat points the lookup at servers of its own: the seat is
        # found only with that redirect lifted, and the send has to happen there too
        seen = []
        self.stack.enter_context(patch.dict(os.environ, {orch.SOCKET_ENV: "suite-socket"}))
        self.stack.enter_context(patch.object(
            orch, "watching", side_effect=lambda _n: orch.SOCKET_ENV not in os.environ))
        self.stack.enter_context(patch.object(
            orch, "find",
            side_effect=lambda _n: seen.append(os.environ.get(orch.SOCKET_ENV)) or self.live()))
        directory = self.failed("run-15")
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(seen, [None])        # looked up where it was found, not in the suite
        self.assertEqual(os.environ[orch.SOCKET_ENV], "suite-socket")

    def test_a_failed_job_goes_back_to_its_seat_instead_of_asking_the_owner(self):
        line = "job j1: 1 task(s) need you"
        self.rows = [self.live()]
        self.assertEqual(run.job_hand_back(SEAT, line, self.logs.append), "sent")
        self.assertEqual(self.typed, [(SEAT, line)])
        # a seat mid-turn is never a reason to ask the owner: the line waits for the tick
        self.screen = "working"
        self.assertEqual(run.job_hand_back(SEAT, line, self.logs.append), "busy")
        self.rows = []
        self.assertEqual(run.job_hand_back(SEAT, line, self.logs.append), "gone")
        self.assertEqual(len(self.typed), 1)

    def test_a_job_whose_seat_was_busy_is_handed_back_by_the_tick(self):
        job_dir = config.JOBS / "job-1"
        job_dir.mkdir(parents=True)
        line = "job job-1: 1 task(s) need you. Result: x. Decide the next step."
        card = "job job-1: 1 task(s) need you"
        pending = {"job_id": "job-1", "seat": SEAT, "tasks": [], "finished_at": 9990,
                   "handback_pending": line, "handback_card": card}
        run.save_job(job_dir, dict(pending))
        self.rows = [self.live()]
        self.screen = "working"
        self.tick()
        self.assertEqual((self.typed, self.cards), ([], []))
        self.assertEqual(run.read_job(job_dir)["handback_pending"], line)
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual(self.typed, [(SEAT, line)])
        self.assertNotIn("handback_pending", run.read_job(job_dir))
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.cards, [])
        # gone by the time the tick gets there: the owner's card is the job's short one and
        # never the typed line, because a path has no place on a card or in the row reading it
        run.save_job(job_dir, dict(pending))
        self.rows = []
        self.tick()
        self.assertEqual([text for _, text, _ in self.cards], [card])
        self.assertNotIn("handback_card", run.read_job(job_dir))

    def test_a_blocked_merge_fixer_ends_the_delivery_retry_blocked(self):
        directory = self.ended("run-16", owner=SEAT, merge_failed=True, no_merge=False,
                               repo=str(self.root), scratch=False, branch="ak/x",
                               base="main", base_sha="a" * 40, rounds=1,
                               round_summaries=[{"round": 1, "verdict": "PASS",
                                                 "done_when": True, "summary": "did it"}],
                               worktree=str(self.root), findings="",
                               review={**self.ended_review(), "head_sha": "b" * 40,
                                       "tree_sha": "c" * 40})
        (directory / "task.md").write_text(
            "# T\n\n## Done when\n```bash\ntrue\n```\n")
        self.rows = [self.live()]
        section = "## Blocked\n\nthe merge target does not exist\n"
        # `ak run merge` runs fixer turns of its own -- the conflict fixer, the final check --
        # and any of them can say the task is wrong; the delivery retry has to end there
        with patch.object(run, "pr_view", return_value=None), \
                patch.object(run, "require_review_pass",
                             side_effect=run.Blocked("the merge target does not exist", section)):
            run.cmd_merge([directory.name])
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        self.assertIn("# BLOCKED \u2014", (directory / "result.md").read_text())
        self.assertIn("finished BLOCKED:", self.typed[-1][1])

    # --- a blocked run on the screens and on `ak run resume` ----------------

    def test_ak_run_resume_refuses_a_blocked_run(self):
        directory = self.blocked_record("run-6")
        with self.assertRaisesRegex(
                config.Error, "blocked runs are not resumed; the orchestrator writes a new task"):
            run.cmd_resume([directory.name])
        self.assertFalse(run.needs_recovery(run.read_state(directory)))
        self.assertFalse(run.unfinished(run.read_state(directory)))

    def test_blocked_reads_with_its_glyph_and_its_reason_on_both_screens(self):
        directory = self.blocked_record("run-7")
        state = run.read_state(directory)
        self.assertEqual(menu.run_state_word(state), "needs you")
        self.assertEqual(run.blocked_note(state),
                         f"{terminal.state_glyph('needs you')} blocked · the checks are wrong")
        _, blocks = menu._runs_table([(directory, state)], 100, 30)
        lines = [terminal.plain(line) for block in blocks for line in block]
        self.assertTrue(any(line.endswith("! needs you") for line in lines), lines)
        self.assertIn(run.blocked_note(state), lines)
        self.assertNotIn("offers resume", "\n".join(lines))
        out = io.StringIO()
        with redirect_stdout(out):
            run.cmd_status([directory.name])
        self.assertIn(run.blocked_note(state), terminal.plain(out.getvalue()))

    def blocked_record(self, name):
        # `recovery_pending` is what a resume leaves behind, so this is the blocked ending of
        # a resumed run: final all the same, and never offered for recovery
        return self.ended(name, owner=SEAT, state="blocked", verdict="BLOCKED",
                          error="the checks are wrong", review=None, recovery_pending=True,
                          blocked="## Blocked\n\nthe checks are wrong\n",
                          rounds=3, round_summaries=[{}])


class BlockedRuns(unittest.TestCase):
    """The real loop, with fake harnesses: a turn that says the task is wrong ends the run."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".handback-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "HANDBACK_FIXTURE": str(self.root)}))
        # nothing outside the fixture is reachable: no tmux server, harness or GitHub
        self.script(self.bin / "tmux", "import sys\nsys.exit(1)\n")
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("post")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers
                             if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def plan(self, **answers):
        (self.root / "plan.json").write_text(json.dumps(answers))

    def launch(self, check="test -f deliverable", rounds=3):
        """One scratch run: the loop is the only thing under test."""
        task = self.root / "task.md"
        task.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# Blocked fixture\n\n"
                        f"## Done when\n```bash\n{check}\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(task), "--exec", self.executor, "--review", self.reviewer])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def calls(self, role):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if row["role"] == role]

    def test_a_blocked_executor_turn_ends_the_run_with_no_reviewer(self):
        self.plan(executor=[BLOCKED_TURN])
        code, directory, state = self.launch()
        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        self.assertEqual(self.calls("reviewer"), [])        # nothing was judged
        self.assertEqual(state["round_summaries"], [])      # and no round was recorded
        self.assertIn("checks a file the task never asks for", state["error"])
        result = (directory / "result.md").read_text()
        self.assertTrue(result.startswith("# BLOCKED — Blocked fixture"), result[:60])
        self.assertIn(BLOCKED_TURN.strip(), result)

    def test_a_blocked_fixer_turn_ends_the_run_the_same_way(self):
        self.plan(reviewer=[FAIL_REVIEW], fixer=[BLOCKED_TURN])
        code, directory, state = self.launch()
        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        # round 1 was reviewed; the fixer that answered it ended the run before round 2
        self.assertEqual(len(self.calls("reviewer")), 1)
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(len(self.calls("fixer")), 1)
        self.assertIn(BLOCKED_TURN.strip(), (directory / "result.md").read_text())

    def test_the_same_checks_failing_the_same_way_end_the_run_blocked(self):
        self.plan(reviewer=[FAIL_REVIEW])
        code, directory, state = self.launch(check="test -f never-written")
        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        self.assertEqual(state["error"], run.BLOCKED_SAME)
        # round 1 recorded its failure and was reviewed; round 2 failed the same way and
        # stopped before the reviewer, so no third attempt was ever spent
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(len(self.calls("reviewer")), 1)
        self.assertEqual(state["done_when_failure"],
                         {"every": [["test -f never-written", ""]]})
        result = (directory / "result.md").read_text()
        self.assertIn(run.BLOCKED_SAME, result)
        self.assertIn("`test -f never-written`", result)

    def test_a_failure_that_changes_goes_on_to_the_next_round(self):
        self.plan(reviewer=[FAIL_REVIEW])
        code, directory, state = self.launch(
            check='printf x >>tries; echo "missing after $(wc -c <tries) tries"; false')
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "fail")           # a FAIL, never a `blocked`
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(len(self.calls("reviewer")), 3)
        self.assertEqual(len(state["done_when_failure"]["every"]), 1)

    def test_a_scratch_run_keeps_its_files_links_each_and_names_its_workspace(self):
        self.plan(reviewer=["VERDICT: PASS\n\n## Findings\n- none\n"])
        odd = "notes/a [draft] (2) #1?%20`<x>.md"
        code, directory, state = self.launch(
            check=f"mkdir -p notes && touch {shlex.quote(odd)} \"$(printf 'two\\nlines')\" "
                  "&& test -f deliverable")
        self.assertEqual((code, state["state"]), (0, "pass"))
        work = Path(state["worktree"])
        files = {path for path in work.rglob("*") if path.is_file()}
        self.assertEqual({path.name for path in files},
                         {"deliverable", Path(odd).name, "two\nlines"})
        # the run is over and its files are still where it made them, each linked by result.md
        result = (directory / "result.md").read_text()
        section = result.split("## Deliverables\n", 1)[1].split("\n\n", 1)[0].splitlines()
        linked = {Path(os.fsdecode(unquote_to_bytes(line.rsplit("](", 1)[1][:-1])))
                  for line in section}
        self.assertEqual(linked, files)
        self.assertIn("- [notes/a \\[draft\\] (2) #1?%20\\`\\<x>.md](", result)
        self.assertIn("- [two%0Alines](", result)
        self.assertIn(f"Result: {directory / 'result.md'}. Workspace: {work}. Decide the next step.",
                      run.handback_line(state, directory))

    def test_a_blocked_section_keeps_its_own_subheadings(self):
        section = run.blocked_section("## Blocked\n\nno token for the registry\n\n"
                                      "### Missing access\n\nthe task assumes one\n")
        self.assertIn("### Missing access", section)
        self.assertIn("the task assumes one", section)
        self.assertEqual(run.blocked_reason(section), "no token for the registry")

    def test_a_blank_line_in_a_command_s_output_does_not_hide_what_it_said(self):
        # `run_done_when` separates records with a blank line; a command that prints one of
        # its own must not have its last word cut off, or two failures would look the same
        first = ("Commit: a\nTree: b\n\n$ check\n[exit 1]\nstarting\n\nE one != two\n\n"
                 "$ lint\n[exit 0]\nfine\n\nstill fine")
        second = first.replace("E one != two", "E three != four")
        self.assertEqual(run.failing_checks(first), [["check", "E one != two"]])
        self.assertEqual(run.failing_checks(second), [["check", "E three != four"]])
        self.assertNotEqual(run.failing_checks(first), run.failing_checks(second))

    def test_a_summary_that_merely_mentions_being_blocked_is_no_blocked_turn(self):
        self.plan(executor=["## Summary\nI was nearly blocked by ## Blocked in the preamble.\n"],
                  reviewer=["VERDICT: PASS\n\n## Findings\n- none\n"])
        code, _, state = self.launch()
        self.assertEqual((code, state["state"]), (0, "pass"))
        self.assertEqual(run.blocked_section("## Summary\nsaid `## Blocked` once"), None)
        self.assertEqual(run.blocked_section("## Blocked\n\nwhy\n\n## Notes\nmore"),
                         "## Blocked\n\nwhy")


if __name__ == "__main__":
    unittest.main(verbosity=2)

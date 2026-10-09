"""On a harness with no stop hook a turn ends by the same rule as on a harness with one.

Muse, OpenCode and Antigravity declare `[stop] enforce = "nudge"`, and the tick types the
continue keystroke at a stop hooks/orchestrator-stop.sh would send back.  A run of the seat's
own parked and undecided holds the stop past a run going, an `ak wait` and a `done` there just
as the hook holds it, and a seat whose `ak wait` names a session that has stopped is told so,
with its reason, before any bare `continue`.  Offline: a fake tmux, fake adapters for the three
harnesses, fake run receipts and a throwaway HOME; the hook runs as its harness runs it, JSON on
stdin.  The seat's turn began once, long ago, and never moves: what is decided here is read off
runs, notices, waits and the screen.  So the hook's two blocks a turn are two nudges for the
same parked run, until a different run parks or the seat has a new notice.
"""

from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, host, job as jobs, menu, notify, orch, plan, run, stop, watch
from agentkit import record

SEAT, OTHER = "acme-api", "fix-api"
HARNESSES = ("muse", "opencode", "antigravity")
# each harness's empty composer row on its prompt screen, and that row holding a typed line
TYPED = {"muse": ("\n\u276f\n", "\n\u276f {}\n"), "antigravity": ("\n>\n", "\n> {}\n"),
         "opencode": ('\u2503  Ask anything\u2026 "What is the tech stack of this project?"',
                      "\u2503  {}")}
SAID = "Here is my recommendation. Let me know if I should continue."
PARKED, THEIRS = "20260101-0800-parked", "20260101-0900-schema"
LATER = "20260101-1000-parked"
TOLD = (f"{OTHER} is now needs you: session closed: press its number to reopen. "
        "Decide the next step.")


class NudgeTurnRule(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in HARNESSES:
            # a model call through any of them fails; the screen rules stay the checkout's own
            script = adapters / f"{harness}.sh"
            script.write_text("#!/bin/sh\nexit 1\n")
            script.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT, config.ADAPTER_DIR_ENV: str(adapters)}))
        for name in (SEAT, OTHER):
            config.save_session(self.cfg, name, "fable", ["opus"], {"cwd": str(self.root)})
        # Only this seat is open: the other session's word comes off its own runs, as it does
        # for the hook, which finds no tmux server at all.
        self.seat = {"name": SEAT, "created": 1, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        listed = lambda *_a, **_k: [dict(self.seat)]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(
            watch, "seat_model", side_effect=lambda _cfg, name, *_a, **_k:
            (self.harness, "meta") if name == SEAT else ("claude", "anthropic")))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.harness, self.pane, self.sent = HARNESSES[0], "", []

    def tmux(self, *args, socket=None, client=False, **_kw):
        """tmux for one seat, answering only the target real tmux answers: `={name}:`."""
        target = args[args.index("-t") + 1] if "-t" in args else None
        if args[0] in ("capture-pane", "send-keys") and target != f"={SEAT}:":
            return 1, f"can't find pane: {target}"
        if args[0] == "capture-pane":
            return 0, self.pane
        if args[0] == "send-keys" and "-l" in args:
            self.sent.append(args[-1])
            empty, row = TYPED[self.harness]    # the line sits in the composer until its Enter
            self.pane = self.screen("prompt").replace(empty, row.format(args[-1]))
        elif args[0] == "send-keys" and args[-1] == "Enter":
            self.pane = self.screen("working")      # the harness took the line and is at work
        return 0, ""

    def screen(self, kind):
        return (REPO / f"tests/fixtures/{self.harness}-{kind}-pane.txt").read_text()

    def stopped(self):
        """The seat at its prompt on words that ask nothing, stood long past STALL_WAIT."""
        now = time.time()
        self.pane = self.screen("prompt")
        # a stop of its own: whatever was typed at the last one is behind it
        watch.seat_write(SEAT, state="at_prompt", turn_began=now - 7200,
                         stop_said_at=now - 3600, stop_nudged=None)

    def tick(self):
        """The two passes this is about, in `watch.main`'s order -- the health pass's end-of-turn
        rule for the seat, then the wait pass -- and the lines the fake tmux was given."""
        before = len(self.sent)
        watch.stop_nudge(self.seat, self.harness, self.pane, notify.last(SEAT),
                         menu.run_records(), False, lambda line: None)
        watch.tell_waits(self.cfg, lambda line: None)
        return self.sent[before:]

    def receipt(self, name, owner, state, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": f"Task {name}", "state": state,
                                   "launched_session": owner, "started_at": time.time() - 86400,
                                   "finished_at": None, **extra})

    def decided(self, name):
        """That parked run decided on: its recovery acknowledged, so `unfinished` lets it go."""
        state = record.read_state(config.RUNS / name)
        record.save_state(config.RUNS / name, {**state, "recovery_acknowledged_at": time.time()})

    def wait(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(watch.wait_main([OTHER]), 0)

    def hook_holds(self, blocks=0):
        """Does hooks/orchestrator-stop.sh send this same stop back, where a harness runs it,
        having sent `blocks` of this turn's stops back already?"""
        home, sockets = self.root / "hook-home", self.root / "sockets"
        sockets.mkdir(mode=0o700, exist_ok=True)
        for name, target in (("state", config.STATE), ("runs", config.RUNS)):
            link = home / ".agentkit" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target)
        (config.STATE / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": watch.seat_read(SEAT)["turn_began"], "blocks": blocks}) + "\n")
        transcript = self.root / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": SAID}]}}) + "\n")
        done = subprocess.run(
            ["bash", str(REPO / "hooks/orchestrator-stop.sh")], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "fake",
                              "transcript_path": str(transcript)}),
            env={"PATH": os.environ["PATH"], "HOME": str(home), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                 "TMUX_TMPDIR": str(sockets)})   # no tmux server this test did not make
        self.assertEqual(done.returncode, 0, done.stderr)
        return '"block"' in done.stdout

    def judged(self, blocks=0):
        """(the hook holds this stop, what the tick types at it): the two always agree."""
        self.stopped()
        return self.hook_holds(blocks), self.tick()

    def test_a_live_job_holds_the_stop_on_every_harness_unless_a_run_is_parked(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                directory = config.JOBS / "one"
                directory.mkdir(parents=True)
                jobs.save_job(directory, {
                    "seat": SEAT, "pid": 42,
                    "process_identity": {"boot": "test-boot", "ticks": 7},
                    "tasks": [{"state": "queued", "run_id": None},
                              {"state": "waiting", "run_id": None}]})
                with patch.object(host, "alive", lambda pid: pid == 42), \
                        patch.object(host, "process_identity",
                                     lambda pid: {"boot": "test-boot", "ticks": 7}):
                    self.stopped()
                    self.assertEqual(self.tick(), [])
                    self.assertEqual(self.tick(), [])
                    self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True,
                                 interruption_reason="The run stopped before recording completion.")
                    self.stopped()
                    self.assertEqual(self.tick(), ["continue"])

    def test_a_parked_run_holds_a_stop_past_a_run_going_a_wait_and_a_done(self):
        for harness in HARNESSES:
            for label, ends_it in (
                    ("a run going", lambda: self.receipt(THEIRS, SEAT, "running")),
                    ("an ak wait", lambda: (self.receipt(THEIRS, OTHER, "running"), self.wait())),
                    ("a done", lambda: notify.record(SEAT, "done", "Shipped the parser"))):
                with self.subTest(harness=harness, case=label):
                    self.setUp()
                    self.harness = harness
                    ends_it()
                    self.assertEqual(self.judged(), (False, []))
                    self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True,
                                 interruption_reason="The run stopped before recording completion.")
                    self.assertEqual(self.judged(), (True, ["continue"]))
                    self.decided(PARKED)
                    self.assertEqual(self.judged(), (False, []))

    def test_b_a_stalled_run_is_going_and_still_parked(self):
        """`going` counts `stalled`, and nothing resumes one: the hook holds the turn on it."""
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.receipt(PARKED, SEAT, "stalled", error="no output for 20 minutes")
                self.assertEqual(self.judged(), (True, ["continue"]))
                self.decided(PARKED)
                self.assertEqual(self.judged(), (False, []))

    def test_c_a_seat_whose_wait_has_ended_is_told_why_before_any_continue(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.receipt(THEIRS, OTHER, "running")
                self.wait()
                self.stopped()
                self.assertEqual(self.tick(), [])       # the other is working: the stop stands
                self.receipt(THEIRS, OTHER, "pass", finished_at=time.time())
                self.assertEqual(self.tick(), [TOLD])   # ... and once it stops, the seat hears why
                self.assertTrue(watch.seat_read(SEAT)["wait"]["told"])
                # the wait is over, and the next stop on nothing is sent back as any other is
                self.stopped()
                self.assertEqual(self.tick(), ["continue"])

    def test_a_live_wait_leaves_the_ticks_completion_binding_untouched(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                notify.record(SEAT, "done", "Shipped the parser")
                self.receipt(THEIRS, OTHER, "running")
                self.wait()
                self.stopped()
                self.assertEqual(self.tick(), [])
                self.assertIsNone(watch.seat_read(SEAT).get("stop_done"))

    def test_d_the_same_parked_run_is_nudged_twice_and_the_third_stop_stands(self):
        """Each `continue` is a turn, so a seat that never decides was nudged forever."""
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True)
                self.assertEqual(self.judged(0), (True, ["continue"]))
                self.assertEqual(self.judged(1), (True, ["continue"]))
                self.assertEqual(self.judged(2), (False, []))
                self.stopped()
                self.assertEqual(self.tick(), [])       # and every stop after it stands too
                # the first is resumed and a different run parks, which is nudged for twice
                self.receipt(PARKED, SEAT, "running")
                self.receipt(LATER, SEAT, "stalled", error="no output for 20 minutes")
                for typed in (["continue"], ["continue"], []):
                    self.stopped()
                    self.assertEqual(self.tick(), typed)
                # the first parks again: it has had its nudges, and swapping them buys no more
                self.receipt(LATER, SEAT, "running")
                self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True)
                self.stopped()
                self.assertEqual(self.tick(), [])
                # the owner is asked and answers: a new notice, and the count starts again
                notify.record(SEAT, "needs", "Resume it?", answered_at=time.time() + 1)
                for typed in (["continue"], ["continue"], []):
                    self.stopped()
                    self.assertEqual(self.tick(), typed)

    def test_e_a_run_a_later_merged_run_replaced_holds_nothing(self):
        """Settled as `ak notify done` and the seat's state read it, on both sides of the rule."""
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                notify.record(SEAT, "done", "Shipped the parser")
                self.receipt(PARKED, SEAT, "fail", recovery_pending=True, branch="ak/parked",
                             finished_at=time.time() - 3600)
                self.assertEqual(self.judged(), (True, ["continue"]))
                self.receipt(LATER, SEAT, "pass", merged=True, finished_at=time.time() - 60,
                             **{"from": "ak/parked"})
                self.assertEqual(self.judged(), (False, []))


    def test_f_finished_work_requires_completion_on_every_harness(self):
        """A completed run is neither a live wait nor a completion declaration."""
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.receipt(THEIRS, SEAT, "pass", started_at=time.time() - 3600,
                             finished_at=time.time() - 60)
                self.assertEqual(self.judged(), (True, ["continue"]))

    def test_failed_and_retired_completions_require_correction_on_every_harness(self):
        for harness in HARNESSES:
            for retired in (False, True):
                with self.subTest(harness=harness, retired=retired):
                    self.setUp()
                    self.harness = harness
                    now = time.time()
                    notify.record(SEAT, "done", "The API is live", time=now - 60, seen=retired)
                    self.receipt(THEIRS, SEAT, "fail", finished_at=now - 30,
                                 reported=True, handed_back=now - 20)
                    self.assertEqual(self.judged(), (True, ["continue"]))
                    self.assertIsNone(watch.seat_read(SEAT).get("stop_done"))

    def test_an_open_plan_holds_completion_on_every_harness(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                notify.record(SEAT, "done", "The API is live")
                config.plan_path(SEAT).write_text(
                    '- [ ] The API repair is live · your eye · acme · written 2026-01-01 12:00\n')
                self.assertEqual(self.judged(), (True, ["continue"]))

    def test_a_hand_kept_plan_holds_completion_on_every_harness(self):
        for harness in HARNESSES:
            for line in ('- [ ] The API repair is live', '  - [ ] The API repair is live'):
                with self.subTest(harness=harness, line=line):
                    self.setUp()
                    self.harness = harness
                    notify.record(SEAT, "done", "Explained the API")
                    config.plan_path(SEAT).write_text(line + '\n')
                    with self.assertRaises(config.Error):
                        plan.require_done(SEAT)
                    self.assertEqual(self.judged(), (True, ["continue"]))
                    config.plan_path(SEAT).write_text(line.replace('[ ]', '[x]') + '\n')
                    self.assertEqual(self.judged(), (False, []))

    def test_quiet_answers_end_only_their_turn_on_every_nudge_harness(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.stopped()
                self.assertEqual(notify.shaped("done", "Explained the API", session=SEAT,
                                               quiet=True), 0)
                self.assertEqual(self.judged(), (False, []))
                self.assertIsNone(notify.last(SEAT, include_seen=True))
                # Different output without a new declaration is unfinished again.
                self.pane = self.screen("prompt").replace("recommendation", "next change")
                watch.seat_write(SEAT, turn_began=time.time() + 1, stop_nudged=None)
                self.assertTrue(self.hook_holds())
                self.assertEqual(self.tick(), ["continue"])

    def test_a_late_working_look_keeps_this_turns_quiet_answer(self):
        for harness in HARNESSES:
            for observed in ("during checks", "after command"):
                with self.subTest(harness=harness, observed=observed):
                    self.setUp()
                    self.harness = harness
                    self.stopped()
                    watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=9990)

                    def working():
                        watch.live_state(self.seat, harness, pane=self.screen("working"),
                                         cfg=self.cfg, now=10001)

                    require_done = plan.require_done

                    def checked(name):
                        proven = require_done(name)
                        if observed == "during checks":
                            working()
                        return proven

                    with patch.object(plan, "require_done", side_effect=checked):
                        self.assertEqual(notify.shaped("done", "Explained the API", session=SEAT,
                                                       quiet=True), 0)
                    if observed == "after command":
                        working()
                    watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10002)
                    with patch.object(watch.time, "time", return_value=10002 + watch.STALL_WAIT + 10):
                        self.assertEqual(self.tick(), [])
                        answer = watch.session_state(
                            SEAT, session=self.seat, cfg=self.cfg, harness=harness,
                            live={"state": "at_prompt"}, records=[],
                            auth_out={}, gh_out={}, token_out={})
                        self.assertEqual(answer["word"], "done")
                        self.assertTrue(answer.get("quiet"))
                        # An actual new prompt retires the answer even without a later look.
                        stop.prompted(SEAT, time.time())
                        self.assertEqual(self.tick(), ["continue"])

    def test_new_open_work_holds_a_previously_quiet_answer(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.stopped()
                self.assertEqual(notify.shaped("done", "Explained the API", session=SEAT,
                                               quiet=True), 0)
                config.plan_path(SEAT).write_text('  - [ ] Repair the API\n')
                self.assertEqual(self.judged(), (True, ["continue"]))
                config.plan_path(SEAT).write_text('  - [x] Repair the API\n')
                self.assertEqual(self.judged(), (False, []))
                self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True)
                self.assertEqual(self.judged(), (True, ["continue"]))

    def test_a_later_observed_turn_requires_its_own_quiet_answer(self):
        for harness in HARNESSES:
            for first_tick in (False, True):
                for same_output in (False, True):
                    with self.subTest(harness=harness, bound=first_tick,
                                      same_output=same_output):
                        self.setUp()
                        self.harness = harness
                        self.stopped()
                        watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=9990)
                        self.assertEqual(notify.shaped("done", "Explained the old API",
                                                       session=SEAT, quiet=True), 0)
                        watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10000)
                        if first_tick:
                            self.assertEqual(self.tick(), [])
                        watch.live_state(self.seat, harness, pane=self.screen("working"),
                                         cfg=self.cfg, now=10010)
                        if not same_output:
                            empty = TYPED[harness][0]
                            self.pane = self.screen("prompt").replace(
                                empty, "A new unfinished change.\n" + empty)
                        watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10011)
                        with patch.object(watch.time, "time", return_value=10011 + watch.STALL_WAIT + 10):
                            word = watch.session_state(
                                SEAT, session=self.seat, cfg=self.cfg, harness=harness,
                                live={"state": "at_prompt"}, records=[],
                                auth_out={}, gh_out={}, token_out={})
                            self.assertNotEqual(word["word"], "done")
                            self.assertEqual(self.tick(), ["continue"])

    def test_changed_output_without_a_working_look_needs_a_new_ending(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.stopped()
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=9990)
                self.assertEqual(notify.shaped("done", "Explained the old API",
                                               session=SEAT, quiet=True), 0)
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10001)
                empty = TYPED[harness][0]
                self.pane = self.screen("prompt").replace(
                    empty, "A new unfinished change.\n" + empty)
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10011)
                with patch.object(watch.time, "time", return_value=10011 + watch.STALL_WAIT + 10):
                    self.assertEqual(self.tick(), ["continue"])

    def test_a_new_quiet_answer_survives_a_late_look_after_an_older_answer(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.stopped()
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=9990)
                self.assertEqual(notify.shaped("done", "Explained the old API",
                                               session=SEAT, quiet=True), 0)
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10001)
                require_done = plan.require_done

                def checked(name):
                    proven = require_done(name)
                    watch.live_state(self.seat, harness, pane=self.screen("working"),
                                     cfg=self.cfg, now=10003)
                    return proven

                with patch.object(watch.time, "time", return_value=10002), \
                        patch.object(plan, "require_done", side_effect=checked):
                    self.assertEqual(notify.shaped("done", "Explained the current API",
                                                   session=SEAT, quiet=True), 0)
                watch.live_state(self.seat, harness, pane=self.pane, cfg=self.cfg, now=10004)
                with patch.object(watch.time, "time", return_value=10004 + watch.STALL_WAIT + 10):
                    self.assertEqual(self.tick(), [])
                    word = watch.session_state(
                        SEAT, session=self.seat, cfg=self.cfg, harness=harness,
                        live={"state": "at_prompt"}, records=[],
                        auth_out={}, gh_out={}, token_out={})
                    self.assertEqual(word["word"], "done")
                    self.assertEqual(word["reason"], "Explained the current API")

    def test_g_a_current_question_stands_past_parked_work(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.receipt(PARKED, SEAT, "interrupted", recovery_pending=True)
                notify.record(SEAT, "needs", "Which account should I use?")
                self.assertEqual(self.judged(), (False, []))


if __name__ == "__main__":
    unittest.main()

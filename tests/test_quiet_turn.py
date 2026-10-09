"""An information answer ends its observed turn, without claiming a finished job.

Drive real hooks and captured hookless panes in the existing private fixtures. No
model, host pane, credentials, process or notification sink outside these homes.
"""

from contextlib import contextmanager, ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, plan, stop, watch
import test_notify as notification_test
import test_nudge_turn_rule as nudge_test
import test_stop_answer as native_test


@contextmanager
def fixture(cls):
    case = cls(methodName="runTest")
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


@contextmanager
def native_home(case):
    with ExitStack() as stack:
        home = case.home / ".agentkit"
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name,
                                home if name == "HOME" else home / name.lower()))
        stack.enter_context(patch.object(config, "CODE", case.home / "code"))
        env = {**case.env(), "AGENTKIT_TMUX_SOCKET": "ak-test-quiet",
               "TMUX_TMPDIR": str(case.home)}
        stack.enter_context(patch.object(case, "env", return_value=env))
        yield env


def quiet_native(case, text="Explained the schema"):
    done = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", "done",
                           text, "--quiet"], capture_output=True, text=True,
                          env={**case.env(), notify.SINK_ENV: "dry-run"}, timeout=30)
    case.assertEqual(done.returncode, 0, done.stderr)
    return done


def row(case):
    return watch.session_state(nudge_test.SEAT, session=case.seat, cfg=case.cfg,
                               records=[], harness=case.harness, live={"state": "at_prompt"},
                               auth_out={}, gh_out={}, token_out={})


def quiet_nudge(case, text="Explained the schema"):
    with redirect_stdout(io.StringIO()):
        case.assertEqual(notify.shaped("done", text, session=nudge_test.SEAT, quiet=True), 0)


class QuietTurn(unittest.TestCase):
    def test_native_acceptance_and_the_next_prompt_use_the_same_quiet_fact(self):
        with fixture(native_test.StopAnswer) as case, native_home(case):
            case.prompt("Explain the schema")  # main's asked escape cannot end this prompt
            self.assertEqual(case.blocked(case.stop())["reason"], native_test.REASON)
            quiet_native(case)
            self.assertEqual(case.stop(), "")
            self.assertIsNone(notify.last(native_test.SEAT, include_seen=True))
            self.assertFalse(config.card_path(native_test.SEAT).exists())
            self.assertEqual(list(notify.outbox().glob("*.json")), [])
            case.prompt("Build the export")
            self.assertEqual(case.blocked(case.stop())["reason"], native_test.REASON)

    def test_a_native_prompt_during_rename_cannot_be_erased_by_the_seat_move(self):
        for during_checks in (False, True):
            with self.subTest(during_checks=during_checks), \
                    fixture(native_test.StopAnswer) as case, native_home(case):
                case.prompt("Explain the schema")
                quiet_native(case)
                began = time.time()
                renamed = "acme-schema"
                old = config.seat_state_path(native_test.SEAT)
                new = config.seat_state_path(renamed)
                replace = Path.replace
                prompted = []

                def move(path, target):
                    if path == old and Path(target) == new:
                        prompted.append(case.prompt("Build the export"))
                    return replace(path, target)

                def rename(_name):
                    with patch.object(Path, "replace", new=move):
                        config.rename_session(native_test.SEAT, renamed)
                    return set()

                if during_checks:
                    with patch.object(plan, "require_done", side_effect=rename), \
                            patch.object(stop.time, "time", return_value=began):
                        self.assertFalse(stop.quiet_done(native_test.SEAT, "Old explanation"))
                else:
                    rename(native_test.SEAT)
                self.assertTrue(prompted)
                answer = watch.session_state(
                    renamed, session={"name": renamed}, cfg={}, records=[], harness="claude",
                    live={"state": "at_prompt"}, auth_out={}, gh_out={}, token_out={})
                self.assertEqual(answer["word"], "needs you")
                self.assertEqual(case.blocked(case.stop())["reason"], native_test.REASON)

    def test_the_first_native_look_must_still_show_the_accepted_answer(self):
        for showing in ("same answer", "changed answer", "appended work"):
            with self.subTest(showing=showing), fixture(native_test.StopAnswer) as case, \
                    native_home(case):
                case.prompt("Explain the schema")
                quiet_native(case)
                text = "The schema has two tables."
                self.assertEqual(case.stop(said=text, background_tasks=[]), "")
                accepted = watch.seat_read(native_test.SEAT)["quiet_done"]["stopped"][0]
                pane = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
                output = "● The schema has\n  two tables."
                if showing == "changed answer":
                    output = "A changed unfinished export"
                elif showing == "appended work":
                    output += "\nA changed unfinished export"
                footer = "                                                                                  ● high"
                pane = pane.replace(footer, output + "\n" + footer)
                watch.live_state({"name": native_test.SEAT}, "claude", pane=pane, cfg={},
                                 now=accepted + 1)
                answer = watch.session_state(
                    native_test.SEAT, now=accepted + 2, session={"name": native_test.SEAT},
                    cfg={}, records=[], harness="claude", live={"state": "at_prompt"},
                    auth_out={}, gh_out={}, token_out={})
                self.assertEqual(bool(answer.get("quiet")), showing == "same answer")
                self.assertIsNone(notify.last(native_test.SEAT, include_seen=True))
                self.assertFalse(config.card_path(native_test.SEAT).exists())

    def test_a_delayed_capture_cannot_retire_an_answer_accepted_after_it_started(self):
        for harness in nudge_test.HARNESSES:
            for accepted_by in ("nudge", "row", "look"):
                for captured in ("working", "old stopped output"):
                    for cached in (False, True):
                        with self.subTest(harness=harness, accepted_by=accepted_by,
                                          captured=captured, cached=cached), \
                                fixture(nudge_test.NudgeTurnRule) as case:
                            case.harness = harness
                            case.stopped()
                            quiet_nudge(case)
                            clock = [10000]

                            def capture(*args, **kwargs):
                                old = (case.screen("working") if captured == "working" else
                                       "Older unfinished output\n" + case.pane)
                                clock[0] = 10010
                                if accepted_by == "nudge":
                                    self.assertEqual(case.tick(), [])
                                elif accepted_by == "row":
                                    self.assertTrue(row(case).get("quiet"))
                                else:
                                    watch.live_state(case.seat, harness, pane=case.pane,
                                                     cfg=case.cfg)
                                clock[0] = 10020
                                return (0, old) if cached else old

                            with patch.object(watch.time, "time", side_effect=lambda: clock[0]):
                                if cached:
                                    # health and typing gates pass along their one captured pane.
                                    with patch.object(nudge_test.orch, "tmux_out", side_effect=capture):
                                        old = watch.pane_text(case.seat)
                                    watch.live_state(case.seat, harness, pane=old, cfg=case.cfg)
                                else:
                                    with patch.object(watch, "pane_text", side_effect=capture):
                                        watch.live_state(case.seat, harness, cfg=case.cfg)
                                if captured == "old stopped output":
                                    self.assertTrue(row(case).get("quiet"))
                                clock[0] = 10030
                                watch.live_state(case.seat, harness, pane=case.pane, cfg=case.cfg)
                                clock[0] = 10400
                                self.assertTrue(row(case).get("quiet"))
                                self.assertEqual(case.tick(), [])

    def test_acceptance_after_the_last_capture_binds_before_another_turn(self):
        for harness in nudge_test.HARNESSES:
            for accepted_by in ("nudge", "row", "look"):
                for next_look in ("working", "changed output"):
                    with self.subTest(harness=harness, accepted_by=accepted_by, next=next_look), \
                            fixture(nudge_test.NudgeTurnRule) as case:
                        case.harness = harness
                        case.stopped()
                        watch.live_state(case.seat, harness, pane=case.pane, cfg=case.cfg, now=9990)
                        quiet_nudge(case)   # after the latest look, before an acceptance
                        accepted = 10000 + watch.STALL_WAIT + 10
                        with patch.object(watch.time, "time", return_value=accepted):
                            if accepted_by == "nudge":
                                self.assertEqual(case.tick(), [])
                            elif accepted_by == "row":
                                self.assertEqual(row(case)["word"], "done")
                            else:
                                watch.live_state(case.seat, harness, pane=case.pane,
                                                 cfg=case.cfg, now=accepted)
                        if next_look == "working":
                            watch.live_state(case.seat, harness, pane=case.screen("working"),
                                             cfg=case.cfg, now=accepted + 10)
                        else:
                            empty, _ = nudge_test.TYPED[harness]
                            changed = case.pane.replace(empty, "New unfinished export\n" + empty)
                            watch.live_state(case.seat, harness, pane=changed,
                                             cfg=case.cfg, now=accepted + 10)
                        # The identical old output cannot bring the earlier answer back.
                        watch.live_state(case.seat, harness, pane=case.pane,
                                         cfg=case.cfg, now=accepted + 11)
                        with patch.object(watch.time, "time",
                                          return_value=accepted + 11 + watch.STALL_WAIT + 10):
                            self.assertEqual(row(case)["word"], "needs you")
                            self.assertEqual(case.tick(), ["continue"])

    def test_the_first_late_working_look_does_not_invalidate_this_turns_answer(self):
        for harness in nudge_test.HARNESSES:
            for during_checks in (False, True):
                with self.subTest(harness=harness, during_checks=during_checks), \
                        fixture(nudge_test.NudgeTurnRule) as case:
                    case.harness = harness
                    case.stopped()
                    watch.live_state(case.seat, harness, pane=case.pane, cfg=case.cfg, now=9990)

                    def working():
                        watch.live_state(case.seat, harness, pane=case.screen("working"),
                                         cfg=case.cfg, now=10001)

                    require_done = plan.require_done

                    def checked(name):
                        proven = require_done(name)
                        if during_checks:
                            working()
                        return proven

                    with patch.object(plan, "require_done", side_effect=checked):
                        quiet_nudge(case)
                    if not during_checks:
                        working()
                    watch.live_state(case.seat, harness, pane=case.pane, cfg=case.cfg, now=10002)
                    with patch.object(watch.time, "time", return_value=10200):
                        self.assertEqual(case.tick(), [])
                        self.assertTrue(row(case).get("quiet"))

    def test_a_new_command_started_before_a_late_look_keeps_its_own_answer(self):
        for harness in nudge_test.HARNESSES:
            with self.subTest(harness=harness), fixture(nudge_test.NudgeTurnRule) as case:
                case.harness = harness
                case.stopped()
                quiet_nudge(case, "Old explanation")
                with patch.object(watch.time, "time", return_value=10010):
                    self.assertTrue(row(case).get("quiet"))
                require_done = plan.require_done

                def checked(name):
                    proven = require_done(name)
                    watch.live_state(case.seat, harness, pane=case.screen("working"),
                                     cfg=case.cfg, now=10020)
                    return proven

                with patch.object(watch.time, "time", return_value=10015), \
                        patch.object(plan, "require_done", side_effect=checked):
                    quiet_nudge(case, "New explanation")
                watch.live_state(case.seat, harness, pane=case.pane, cfg=case.cfg, now=10030)
                # An older capture must not retire this newer stopped answer.
                watch.live_state(case.seat, harness, pane=case.screen("working"),
                                 cfg=case.cfg, now=10025)
                with patch.object(watch.time, "time", return_value=10400):
                    answer = row(case)
                    self.assertTrue(answer.get("quiet"))
                    self.assertEqual(answer["reason"], "New explanation")

    def test_an_older_command_cannot_overwrite_a_newer_answer(self):
        with fixture(nudge_test.NudgeTurnRule) as case:
            case.stopped()

            def checked(name):
                with patch.object(plan, "require_done", return_value=set()), \
                        patch.object(stop.time, "time", return_value=10010):
                    self.assertTrue(stop.quiet_done(name, "New explanation"))
                return set()

            with patch.object(plan, "require_done", side_effect=checked):
                self.assertFalse(stop.quiet_done(nudge_test.SEAT, "Old explanation"))
            with patch.object(stop.time, "time", return_value=10020):
                self.assertEqual(row(case)["reason"], "New explanation")

    def test_new_open_work_holds_a_quiet_answer_on_every_acceptance_path(self):
        with fixture(nudge_test.NudgeTurnRule) as case:
            case.stopped()
            quiet_nudge(case)
            plan.path(nudge_test.SEAT).write_text("- [ ] Build the export\n")
            self.assertIsNone(stop.quiet_ending(nudge_test.SEAT))
            self.assertFalse(stop.recorded_ending(nudge_test.SEAT, records=[])[0])
            self.assertEqual(row(case)["word"], "needs you")
            self.assertEqual(case.tick(), ["continue"])
            with self.assertRaises(notify.Refused):
                quiet_nudge(case)

    def test_the_quiet_command_leaves_every_ordinary_notification_record_unchanged(self):
        for prior in ("empty", "pending", "question", "retired", "sent"):
            with self.subTest(prior=prior), fixture(notification_test.Notifications) as case:
                if prior != "empty":
                    notify.record("seat", "needs" if prior == "question" else "done",
                                  "Which export?" if prior == "question" else "Export shipped",
                                  runs=["acme-run"], seen=prior == "retired",
                                  completion={"created": 1, "outcomes": [["Export shipped"]]})
                    notify._card_write("seat", {"word": "done", "since": 1, "began": 1,
                                               "episode": "ordinary", "sent": prior == "sent"})
                paths = (config.notify_path("seat"), config.card_path("seat"))
                before = [path.read_bytes() if path.exists() else None for path in paths]
                events = list(notify.outbox().glob("*.json"))
                case.cli("done", "Explained the schema", "--quiet")
                self.assertEqual([p.read_bytes() if p.exists() else None for p in paths], before)
                self.assertEqual(list(notify.outbox().glob("*.json")), events)
                self.assertEqual(case.requests, [])

    def test_a_pending_jobs_first_ordinary_alert_survives_quiet_answers_and_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed), fixture(notification_test.Notifications) as case:
                pending = config.RUNS / "acme-run"
                pending.mkdir()
                state = {"run_id": pending.name, "state": "running", "launched_session": "seat",
                         "started_at": time.time(), "pid": 0}
                path = pending / "run.json"
                path.write_text(json.dumps(state))
                case.cli("done", "Export shipped")
                before = config.notify_path("seat").read_bytes()
                case.cli("done", "Explained why it waits", "--quiet")
                self.assertEqual(config.notify_path("seat").read_bytes(), before)
                self.assertEqual(case.cards("done"), [])
                if failed:
                    state.update(state="fail", verdict="FAIL", reported=True,
                                 finished_at=time.time())
                    path.write_text(json.dumps(state))
                    self.assertEqual(notify.transition("seat", log=lambda _: None), 0)
                    self.assertEqual(case.cards("done"), [])
                    case.cli("done", "Explained the retry", "--quiet")
                state.update(state="pass", verdict="PASS", reported=True, finished_at=time.time())
                path.write_text(json.dumps(state))
                if failed:
                    case.cli("done", "Export shipped")
                self.assertEqual(notify.transition("seat"), 0)
                self.assertEqual(len(case.cards("done")), 1)
                self.assertEqual(notify.last("seat")["text"], "Export shipped")

    def test_answered_question_edits_retry_after_card_loss_without_a_done_card(self):
        with fixture(notification_test.Notifications) as case:
            case.cli("needs", "Which export format?")
            notify.answered("seat", time.time())
            self.assertIsNone(notify.last("seat"))
            case.cli("done", "Explained the format", "--quiet")
            events = list(notify.outbox().glob("*.json"))
            case.edit_status = 503
            for _ in range(2):
                config.card_path("seat").unlink(missing_ok=True)
                self.assertEqual(notify.transition("seat"), 0)
            before = len(case.requests)
            case.edit_status = 200
            for _ in range(2):
                self.assertEqual(notify.transition("seat"), 0)
                notify.retry_pending(log=lambda _: None)
            self.assertTrue(any(method == "PATCH" and payload["embeds"][0]["title"]
                                == "Answered · seat" for method, _, payload in case.requests[before:]))
            self.assertEqual(notify.last("seat", include_seen=True)["open_needs"], [])
            self.assertEqual(notify._card_read("seat")["open_needs"], [])
            self.assertEqual(case.cards("done"), [])
            self.assertEqual(list(notify.outbox().glob("*.json")), events)
            case.cli("done", "Export shipped")
            self.assertEqual(len(case.cards("done")), 1)

    def test_quiet_dry_runs_and_workers_change_no_state(self):
        with fixture(notification_test.Notifications) as case:
            case.cli("done", "Explained the schema", "--quiet", "--dry-run")
            case.cli("done", "Explained the schema", "--quiet", env={"AK_RUN_ROLE": "worker"})
            self.assertEqual(watch.seat_read("seat"), {})
            self.assertIsNone(notify.last("seat", include_seen=True))
            self.assertFalse(config.card_path("seat").exists())
            self.assertEqual(list(notify.outbox().glob("*.json")), [])
            self.assertEqual(case.requests, [])


if __name__ == "__main__":
    unittest.main()

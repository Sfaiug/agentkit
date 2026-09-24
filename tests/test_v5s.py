"""v5s: a dead orchestrator seat is reopened and told to continue, by the run and by the tick.

Offline: no tmux (`orch.sessions`/`orch.listing` say what the seat is), a fake `ensure`, a
fake confirmed send and a fake notify.  The one test of the real `ensure(saved=True)` and
`resume(hand_over=False)` fakes the launch itself and forbids an attach.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import re
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, notify, orch, run, watch

SEAT = "seat"
REAL_ENSURE = orch.ensure


class V5s(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": ""}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.rows = []       # what tmux holds, as the listing and a lookup report it
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        self.stack.enter_context(patch.object(orch, "listing", lambda *_a, **_k: list(self.rows)))
        self.stack.enter_context(patch.object(
            orch, "tmux_out", side_effect=AssertionError("tmux was called")))
        self.stack.enter_context(patch.object(run, "launcher_watched", return_value=False))
        self.logs, self.typed, self.cards, self.slept, self.reopened = [], [], [], [], []
        self.back = "resumed"    # what the fake `ensure` answers, or the error it raises
        self.sent = True         # what the fake confirmed send answers

        def ensure(cfg, name, log=print, saved=False):
            self.reopened.append((name, saved))
            if isinstance(self.back, Exception):
                raise self.back
            return self.back
        self.stack.enter_context(patch.object(orch, "ensure", side_effect=ensure))
        self.stack.enter_context(patch.object(
            watch, "type_into",
            side_effect=lambda session, text, log: self.typed.append(
                (session.get("name"), text)) or self.sent))
        self.stack.enter_context(patch.object(
            notify, "shaped",
            side_effect=lambda kind, text, **kw: self.cards.append((kind, text, kw)) or 0))
        self.stack.enter_context(patch.object(watch.time, "sleep", self.slept.append))
        self.record()

    def record(self):
        config.save_session(self.cfg, SEAT, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": "thread-seat", "id_source": orch.LAUNCHER})

    def going(self, name="run-2", state="running"):
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "title": "Going", "state": state,
                                   "launched_session": SEAT, "pid": os.getpid(),
                                   "started_at": 1, "reported": False})
        return directory

    def exited(self, **extra):
        return {"name": SEAT, "path": str(self.root), "created": 1, "attached": False,
                "exited": True, "legacy": False, "resumable": False, **extra}

    def live(self):
        return self.exited(exited=False)

    def old_needs(self, verdict="PASS", name="run-1"):
        return (f"Its orchestrator session {SEAT} is gone. Run finished: {verdict}. "
                f"Press n in the menu, then say: continue Finished {name}.")

    # (a) a finished run with its seat gone reopens the seat and types the continue line

    def test_v5s_a_finished_run_reopens_its_gone_seat_and_types_the_continue_line(self):
        directory = self.ended("run-1", owner=SEAT)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(self.slept, [watch.INBOX_WARMUP])
        self.assertEqual(self.typed, [(SEAT, "continue Finished run-1: run run-1 finished PASS, "
                                             f"result at {directory / 'result.md'}")])
        self.assertEqual(self.cards, [])
        state = run.read_state(directory)
        self.assertTrue(state["reported"])
        self.assertNotIn("notification_pending", state)

    def test_v5s_a_seat_that_came_back_fresh_is_told_so_and_a_live_one_is_not_warmed_up(self):
        directory = self.ended("run-1", owner=SEAT)
        self.back = "fresh"
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertTrue(self.typed[-1][1].endswith(f"result at {directory / 'result.md'}"
                                                   + watch.FRESH_NOTE), self.typed)
        self.assertIn("could not be resumed", watch.FRESH_NOTE)
        # a seat somebody brought back between the look and the reopen: typed into at once
        self.back = False
        self.slept.clear()
        failed = self.ended("run-3", owner=SEAT, state="fail")
        run.announce(run.read_state(failed), failed, self.logs.append)
        self.assertEqual(self.slept, [])
        self.assertEqual(self.typed[-1], (SEAT, "continue Finished run-3: run run-3 finished FAIL, "
                                                f"result at {failed / 'result.md'}"))
        self.assertEqual(self.cards, [])

    # (b) when `ensure` fails, the needs goes out with the added sentence

    def test_v5s_a_seat_that_cannot_be_started_sends_the_needs_with_the_added_sentence(self):
        directory = self.ended("run-1", owner=SEAT)
        self.back = config.Error(f"tmux could not start the session {SEAT} in /gone: no server")
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(self.typed, [])
        self.assertEqual(self.cards, [("needs", self.old_needs() + " agentkit tried to reopen the "
                                       f"seat and could not: tmux could not start the session "
                                       f"{SEAT} in /gone: no server",
                                       {"session": SEAT, "event_id": "orphan:run-1:None:9990"})])
        self.assertTrue(run.read_state(directory)["reported"])

    # (c) when the line is not confirmed sent, the same

    def test_v5s_an_unconfirmed_continue_line_sends_the_needs_with_the_added_sentence(self):
        directory = self.ended("run-1", owner=SEAT)
        self.sent = False
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(len(self.typed), 1)
        self.assertEqual([card[1] for card in self.cards],
                         [self.old_needs() + " agentkit tried to reopen the seat and could not: "
                          "the continue line was not confirmed sent"])

    # (d) a seat that died mid-run is reopened by the tick once, with the marker

    def test_v5s_the_tick_reopens_a_seat_that_died_mid_run_once_per_death(self):
        self.going("run-2")
        self.ended("run-1", owner=SEAT)          # an ending is announce's, never the tick's
        self.rows = [self.exited()]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(self.slept, [watch.INBOX_WARMUP])
        self.assertEqual(self.typed, [(SEAT, "continue: your run run-2 (Going) is still going; "
                                             "pick up where you left off")])
        self.assertEqual(self.cards, [])
        self.assertTrue(watch.seat_read(SEAT)["reopened_at"])
        # the next tick finds the same death and leaves it alone
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(len(self.reopened), 1)
        # seen live: the marker goes, and the next death is a new one
        self.rows = [self.live()]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertFalse(watch.seat_read(SEAT).get("reopened_at"))
        self.assertEqual(len(self.reopened), 1)
        self.rows = [self.exited(restart="starts fresh")]
        self.back = "fresh"
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(len(self.reopened), 2)
        self.assertTrue(self.typed[-1][1].endswith("pick up where you left off" + watch.FRESH_NOTE))
        # a seat with nothing going is not reopened at all
        self.rows = [self.exited(name="other")]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(len(self.reopened), 2)
        self.assertEqual(self.cards, [])

    def test_v5s_the_tick_asks_tmux_only_with_a_run_going_or_a_marker_to_clear(self):
        asked = []
        self.stack.enter_context(patch.object(
            orch, "listing", side_effect=lambda *_a, **_k: asked.append(1) or list(self.rows)))
        self.ended("run-1", owner=SEAT)          # an ending, and nothing going: tmux is left alone
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(asked, [])
        # a marker left by a death whose run has since finished still has to be cleared
        watch.seat_write(SEAT, reopened_at=5)
        self.rows = [self.live()]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(len(asked), 1)
        self.assertFalse(watch.seat_read(SEAT).get("reopened_at"))
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual((len(asked), self.reopened, self.cards), (1, [], []))

    def test_v5s_the_tick_tells_the_owner_only_when_the_reopen_fails(self):
        self.going("run-2", state="queued")
        self.rows = [self.exited()]
        self.back = config.Error("no session 'seat' to reopen and no record of one")
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])
        self.assertEqual(self.typed, [])
        self.assertEqual(len(self.cards), 1)
        kind, text, extra = self.cards[0]
        self.assertEqual((kind, text), ("needs", (
            f"Its orchestrator session {SEAT} is gone while run run-2 (Going) is still going. "
            "agentkit tried to reopen the seat and could not: no session 'seat' to reopen and "
            "no record of one. Press its number in the menu, then say: continue Going.")))
        self.assertEqual(extra["session"], SEAT)
        self.assertTrue(extra["event_id"].startswith(f"revive:{SEAT}:run-2:"))
        # once: the marker stands until the seat is seen live
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual((len(self.reopened), len(self.cards)), (1, 1))

    # (e) a seat stopped on purpose is not reopened by either path

    def test_v5s_a_seat_stopped_on_purpose_is_not_reopened_by_either_path(self):
        orch.cmd_stop([SEAT])
        self.assertTrue(watch.seat_read(SEAT)["stopped_at"])
        self.assertTrue(watch.seat_read(SEAT)["closed_by_owner"])
        self.record()             # the marker alone has to carry the decision
        directory = self.ended("run-1", owner=SEAT)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [])
        # a seat the owner closed keeps its ending waiting, never a revival nor a card
        self.assertEqual((self.typed, self.cards), ([], []))
        state = run.read_state(directory)
        self.assertFalse(state["handed_back"])
        self.assertTrue(state["handback_pending"])
        self.assertEqual(state["handback_wait_reason"], "session closed by the owner")
        self.going("run-2")
        self.rows = [self.exited()]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual((self.reopened, self.typed, len(self.cards)), ([], [], 0))
        # a seat launched under the name again is not the stopped one
        with patch.object(orch, "start"):
            orch.launch(SEAT, "fable", self.root, ["fable"], "thread-seat")
        self.assertFalse(watch.seat_read(SEAT).get("stopped_at"))
        self.assertFalse(watch.seat_read(SEAT).get("closed_by_owner"))
        self.rows = []
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.reopened, [(SEAT, True)])

    def test_v5s_nothing_to_reopen_keeps_the_notice_as_it_was(self):
        # neither a pane nor a record: stopped, forgotten or never agentkit's to open
        config.session_path(SEAT).unlink()
        directory = self.ended("run-1", owner=SEAT)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.reopened, self.typed), ([], []))
        self.assertEqual([card[1] for card in self.cards], [self.old_needs()])
        self.assertEqual(self.logs, [f"the orchestrator session {SEAT} this run was launched from "
                                     "is gone; asking the user to continue the task"])

    # (f) the log lines read as specified

    def test_v5s_the_log_lines_read_as_specified(self):
        directory = self.ended("run-1", owner=SEAT)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.logs, [
            f"the orchestrator session {SEAT} this run was launched from is gone; reopening it",
            f"reopened {SEAT} and asked it to continue run-1"])
        self.logs.clear()
        self.going("run-2")
        self.rows = [self.exited()]
        watch.revive_seats(self.cfg, self.logs.append)
        self.assertEqual(self.logs, [f"reopened {SEAT} and asked it to continue run-2"])
        self.logs.clear()
        self.back = config.Error("cannot resume the session seat: no pane")
        failed = self.ended("run-3", owner=SEAT)
        run.announce(run.read_state(failed), failed, self.logs.append)
        self.assertEqual(self.logs, [
            f"the orchestrator session {SEAT} this run was launched from is gone; reopening it",
            f"the orchestrator session {SEAT} this run was launched from is gone; asking the "
            "user to continue the task"])

    # the real `ensure(saved=True)`: the seat's own conversation, in its own pane, no attach

    def test_v5s_ensure_saved_brings_back_the_seats_own_conversation_and_never_attaches(self):
        launched = []
        self.stack.enter_context(patch.object(orch, "attach",
                                              side_effect=AssertionError("attached")))
        self.stack.enter_context(patch.object(orch, "launch",
                                              side_effect=lambda *args: launched.append(args)))
        self.stack.enter_context(patch.object(
            orch, "command", side_effect=lambda cfg, model, conversation=None, fresh=False: [
                model, "--session-id" if fresh else "--resume", conversation]))
        # tmux lost the seat: the record brings it back, fresh until its harness has opened
        # the conversation it was given, and then on that conversation
        self.assertEqual(REAL_ENSURE(self.cfg, SEAT, self.logs.append, saved=True), "fresh")
        self.assertEqual(launched[-1][:2], (SEAT, "fable"))
        self.assertEqual(launched[-1][3], ["fable", "--session-id", "thread-seat"])
        self.assertIsNone(launched[-1][5])
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        transcript = self.root / ".claude" / "projects" / slug / "thread-seat.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}\n")
        self.assertEqual(REAL_ENSURE(self.cfg, SEAT, self.logs.append, saved=True), "resumed")
        self.assertEqual(launched[-1][3], ["fable", "--resume", "thread-seat"])
        self.assertIn(f"orch: resuming {SEAT} on fable in {self.root} (conversation thread-seat)",
                      self.logs)
        # tmux still holds the exited pane: respawned in it
        self.rows = [self.exited()]
        self.assertEqual(REAL_ENSURE(self.cfg, SEAT, self.logs.append, saved=True), "resumed")
        self.assertEqual(launched[-1][5], self.rows[0])
        # live: nothing to bring back
        self.rows = [self.live()]
        self.assertFalse(REAL_ENSURE(self.cfg, SEAT, self.logs.append, saved=True))
        self.assertEqual(len(launched), 3)
        # neither a pane nor a record: an error, never a fresh seat by that name
        self.rows = []
        config.session_path(SEAT).unlink()
        with self.assertRaises(config.Error):
            REAL_ENSURE(self.cfg, SEAT, self.logs.append, saved=True)
        self.assertEqual(len(launched), 3)


if __name__ == "__main__":
    unittest.main()

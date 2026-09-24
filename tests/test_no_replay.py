"""No replay of history, and no hand-back that wakes a seat the owner closed.

Offline.  The seat is faked (no tmux: `orch.sessions`/`listing` say what is
there, `watch.live_state` says what its screen shows) and the confirmed send,
and the real `run.announce` and the real `ak watch` tick are driven.
"""

from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import os
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import browser, config, menu, notify, orch, run, watch

SEAT = "seat"


class NoReplay(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": ""}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.rows = []
        self.screen = "at_prompt"
        self.rule = "prompt.composer"
        self.pane = "\u276f\n"
        self.sent = True
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
            side_effect=lambda session, text, log, *_: self.typed.append(
                (session.get("name"), text)) or self.sent))
        self.stack.enter_context(patch.object(
            notify, "shaped",
            side_effect=lambda kind, text, **kw: self.cards.append((kind, text, kw)) or 0))
        self.stack.enter_context(patch.object(notify, "tick_cards"))
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
        with guard() as held:
            if veto(held if held is not None else session["name"]):
                return False
        typed()
        self.typed.append((session["name"], text))
        return self.sent

    def live(self):
        return {"name": SEAT, "path": str(self.root), "created": 1, "attached": False,
                "exited": False, "legacy": False, "resumable": False}

    def fresh(self, name, **extra):
        now = time.time()
        return self.ended(name, owner=SEAT, finished_at=now, started_at=now - 10, **extra)

    def tick(self):
        with patch.object(watch, "health"), patch.object(watch, "recover_runs"), \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                patch.object(run, "schedule_gc"), patch.object(browser, "tidy"), \
                patch.object(orch, "stamp"), patch.object(orch, "sweep"):
            self.assertEqual(watch.main([]), 0)

    def test_first_tick_after_upgrade_marks_old_endings_without_typing_or_reopening(self):
        first = self.ended("old-1", owner=SEAT, finished_at=1000)
        second = self.ended("old-2", owner=SEAT, finished_at=2000)
        self.rows = []
        logs = []
        self.assertEqual(watch.sweep_preexisting(logs.append), 2)
        self.assertEqual(len(logs), 1)
        self.assertIn("marked 2 pre-existing endings", logs[0])
        self.assertIn("not replayed", logs[0])
        self.assertIn("old-1", logs[0])
        self.assertIn("old-2", logs[0])
        for directory in (first, second):
            state = run.read_state(directory)
            self.assertTrue(state["handed_back"])
            self.assertEqual(state["handback_note"], "pre-existing ending; not replayed")
            self.assertFalse(run.owes_ending(state))
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))
        self.tick()
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))

    def test_ending_younger_than_an_hour_is_delivered(self):
        directory = self.fresh("run-new")
        self.rows = [self.live()]
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(len(self.typed), 1)
        self.assertIn("finished PASS", self.typed[0][1])
        state = run.read_state(directory)
        self.assertTrue(state["handed_back"])
        self.assertNotIn("handback_note", state)

    def test_seat_with_closed_by_owner_is_not_reopened_and_handback_waits(self):
        directory = self.fresh("run-wait")
        self.rows = []
        watch.seat_write(SEAT, closed_by_owner=True)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.reopened, self.typed, self.cards), ([], [], []))
        state = run.read_state(directory)
        self.assertFalse(state["handed_back"])
        self.assertTrue(state["handback_pending"])
        self.assertEqual(state["handback_wait_reason"], "session closed by the owner")
        self.assertTrue(run.owes_ending(state))
        # an hour later the wait is still a wait, not history: the sweep leaves seen endings
        logs = []
        self.assertEqual(watch.sweep_preexisting(logs.append, now=time.time() + 7200), 0)
        self.assertEqual(logs, [])
        state = run.read_state(directory)
        self.assertTrue(state["handback_pending"])
        self.assertTrue(run.owes_ending(state))
        found = watch.session_state(SEAT, session={"name": SEAT, "exited": True},
                                    cfg=self.cfg, number=1)
        self.assertIn("session closed by the owner", found["reason"])
        self.assertIn("hand-backs waiting", found["reason"])

    def test_reopening_the_seat_delivers_it(self):
        directory = self.fresh("run-back")
        self.rows = []
        watch.seat_write(SEAT, closed_by_owner=True)
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [])
        # the seat stays closed longer than an hour: the wait ages but is still delivered
        aged = run.read_state(directory)
        aged["finished_at"] = 1000
        run.save_state(directory, aged)
        self.assertEqual(watch.sweep_preexisting(self.logs.append), 0)
        self.assertTrue(run.read_state(directory)["handback_pending"])
        with patch.object(orch, "start"):
            orch.launch(SEAT, "fable", self.root, ["fable"], "thread-seat")
        self.assertFalse(watch.seat_read(SEAT).get("closed_by_owner"))
        self.rows = [self.live()]
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertIn("run-back", self.typed[0][1])
        state = run.read_state(directory)
        self.assertTrue(state["handed_back"])
        self.assertNotIn("handback_pending", state)
        self.assertNotIn("handback_note", state)

    def test_a_reboot_leaves_a_seat_the_owner_closed_closed(self):
        # A pause script ends a seat and leaves its record: after a reboot the tick brings
        # back every seat with a proven conversation, but never one he closed himself --
        # reopening it would clear his mark and put a card on his phone.
        orch.mark_owner_closed(SEAT)
        watch.save_state({**watch.load_state(), "boot_id": "before"})
        with patch.object(watch, "boot_id", return_value="after"), \
                patch.object(orch, "resume", side_effect=AssertionError("reopened")):
            watch.resume_after_boot(self.cfg, log=self.logs.append)
        self.assertEqual(watch.load_state()["boot_id"], "after")
        self.assertTrue(watch.seat_read(SEAT)["closed_by_owner"])
        self.assertEqual((self.typed, self.cards), ([], []))
        # the same seat, not closed by him, is brought back by the next boot
        watch.seat_write(SEAT, stopped_at=None, closed_by_owner=None)
        with patch.object(watch, "boot_id", return_value="again"), \
                patch.object(orch, "resume", return_value="fresh") as resume:
            watch.resume_after_boot(self.cfg, log=self.logs.append)
        self.assertEqual([call.args[1] for call in resume.call_args_list], [SEAT])

    def test_the_tick_tells_a_seat_reopened_mid_turn_to_continue(self):
        # a menu's boot pass reopened it mid-turn and marked it; the tick is what types
        self.rows = [self.live()]
        watch.seat_write(SEAT, midturn={"boot": watch.boot_id(), "at": time.time() - 60,
                                        "name": SEAT})
        self.tick()
        self.assertEqual(self.typed, [(SEAT, watch.MIDTURN_LINE)])
        self.assertIsNone(watch.seat_read(SEAT)["midturn"])

    def test_x_sets_closed_by_owner(self):
        orch.cmd_stop([SEAT])
        self.assertTrue(watch.seat_read(SEAT)["stopped_at"])
        self.assertTrue(watch.seat_read(SEAT)["closed_by_owner"])
        config.save_session(self.cfg, SEAT, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": "thread-seat", "id_source": orch.LAUNCHER})
        watch.seat_write(SEAT, stopped_at=None, closed_by_owner=None)
        with patch.object(menu.terminal, "ask", return_value=SEAT), \
                patch.object(menu, "read", return_value="y"), \
                patch.object(menu.terminal, "frame", lambda *a, **k: None):
            menu.stop_session([{"name": SEAT}], dry_run=False)
        self.assertTrue(watch.seat_read(SEAT)["closed_by_owner"])
        watch.seat_write(SEAT, stopped_at=None, closed_by_owner=None)
        orch.mark_owner_closed(SEAT)
        self.assertTrue(watch.seat_read(SEAT)["closed_by_owner"])

    def test_ak_run_status_lists_the_waiting_handbacks(self):
        directory = self.fresh("run-pending")
        self.rows = []
        watch.seat_write(SEAT, closed_by_owner=True)
        run.announce(run.read_state(directory), directory, self.logs.append)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status(["--pending"]), 0)
        self.assertIn("run-pending", out.getvalue())
        self.assertIn("hand-back waiting", out.getvalue())
        self.assertIn("session closed by the owner", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([]), 0)
        self.assertIn("hand-back waiting", out.getvalue())

    def test_orphan_grace_keeps_a_long_dead_seat_closed(self):
        directory = self.fresh("run-old-death")
        self.rows = []
        config.update_session(SEAT, seen=5000)
        self.assertFalse(watch.orphan_fresh(run.read_state(directory), SEAT))
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.reopened, self.typed), ([], []))
        self.assertEqual(len(self.cards), 1)
        self.assertNotIn("tried to reopen", self.cards[0][1])

    def test_stuck_card_on_history_retries_without_reopening(self):
        directory = self.ended("run-card", owner=SEAT, finished_at=1000,
                               notification_pending=True)
        self.rows = []
        self.assertTrue(watch.is_preexisting(run.read_state(directory)))
        self.assertTrue(watch.orphan_fresh(run.read_state(directory), SEAT))
        self.assertEqual(watch.sweep_preexisting(self.logs.append), 0)
        self.assertTrue(run.read_state(directory)["notification_pending"])
        run.announce(run.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.reopened, self.typed), ([], []))
        self.assertEqual(len(self.cards), 1)
        self.assertNotIn("tried to reopen", self.cards[0][1])
        state = run.read_state(directory)
        self.assertTrue(state["reported"])
        self.assertNotIn("handback_note", state)


if __name__ == "__main__":
    unittest.main()

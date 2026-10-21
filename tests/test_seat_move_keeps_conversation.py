"""A seat moved to another model of its harness goes on with its conversation, and its bar names
the new model from the moment the new harness is up.

Offline: a temporary HOME and an invented seat, with tmux, the adapters and orch's clock faked;
no real seat, process or transcript is touched.
"""

from datetime import datetime, timezone
import json
import threading
import time
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, statusbar, watch
from agentkit.harness import claude

SEAT = "acme-fix"
OWN = "0f5d6e2a-6a43-4c3e-9b0e-3a1f6c2d9e10"      # the conversation the seat's launch handed out
NOW = 20000


def capture(name):
    return (REPO / "tests/fixtures" / name).read_text(encoding="utf-8", errors="replace")


class Stopped(Clock):
    """`time` as orch sees it, its clock stopped at NOW."""

    def time(self):
        return NOW


class Ticking(Clock):
    """`time` as orch sees it, a second later at every reading."""

    def __init__(self, sleep):
        super().__init__(sleep)
        self.now = NOW

    def time(self):
        self.now += 1
        return self.now


class SeatMove(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"],
                            {"cwd": str(self.root), "conversation": OWN,
                             "id_source": "launcher", "resumable": True})
        self.seat = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}
        self.respawned, self.bar, self.refused = [], [], None
        self.pane = capture("claude-prompt-pane.txt")

        def adapter(cfg, model, conversation=None, fresh=False, **_kw):
            if fresh and conversation and config.model(cfg, model)["harness"] != "claude":
                return None                      # only Claude Code is told an id to open
            return ["acme-tui", model, *([conversation] if conversation else []),
                    *(["new"] if fresh else [])]

        def tmux(*args, **_kw):
            if args[0] == "show-options":
                return 0, "%7"
            if args[0] == "display-message":
                return 0, SEAT
            if args[0] == "capture-pane":
                return 0, self.pane
            if args[0] == "respawn-pane":
                # a tick redraws the bar as the new harness comes up
                statusbar.redress(self.seat, {"word": "working"}, cfg=self.cfg)
                return (1, self.refused) if self.refused else (0, "")
            return 1, ""                         # no server to list or write

        for name, fake in (("_switch_plan", lambda *_a, **_kw: ("", None)),
                           ("find", lambda *_a, **_kw: self.seat),
                           ("command", adapter),
                           ("opened", lambda *_a, **_kw: True),
                           ("seat_command", lambda _name, cmd, *_a: self.respawned.append(cmd)
                            or "true"),
                           ("tmux_out", tmux),
                           ("tmux_lists", lambda *_a, **_kw: (0, ""))):
            self.stack.enter_context(patch.object(orch, name, side_effect=fake))
        self.stack.enter_context(patch.object(orch, "time", Stopped(time.sleep)))
        self.stack.enter_context(patch.object(
            statusbar, "_write",
            side_effect=lambda _name, model, *_a, every=False, **_kw: self.bar.append(
                (model, "dress" if every else "redress"))))

    def move(self, model):
        return orch.switch_orchestrator(self.cfg, SEAT, model, providers={})

    def record(self):
        return config.session_records()[SEAT]

    def test_a_claude_seat_moved_to_another_claude_model_resumes_its_conversation(self):
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.respawned, [["acme-tui", "fable", OWN]])   # resumed, not opened
        self.assertEqual((self.record()["orchestrator"], self.record()["conversation"]),
                         ("fable", OWN))
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))         # no handover typed

    def test_moved_to_another_harness_it_opens_fresh_with_the_handover(self):
        self.assertEqual(self.move("astra"), "")
        [cmd] = self.respawned
        self.assertEqual(cmd[-2:], ["acme-tui", "astra"])     # after its launch receipt's env
        self.assertEqual(self.record()["orchestrator"], "astra")
        self.assertIn("You took over this seat from opus",
                      watch.seat_read(SEAT)["midturn"]["line"])

    def test_a_conversation_its_harness_cannot_resume_opens_fresh_with_the_handover(self):
        config.update_session(SEAT, id_source=None)     # nothing the launcher handed out
        self.assertEqual(self.move("fable"), "")
        [cmd] = self.respawned
        self.assertEqual((cmd[:2], cmd[-1]), (["acme-tui", "fable"], "new"))
        self.assertNotEqual(cmd[2], OWN)
        self.assertIn("You took over this seat from opus",
                      watch.seat_read(SEAT)["midturn"]["line"])

    def test_a_seat_moved_mid_turn_is_told_to_go_on(self):
        watch.seat_write(SEAT, state="at_prompt")     # its last reading, a prompt behind
        config.record_hook_fact(SEAT, {"session": SEAT, "event": "UserPromptSubmit",
                                       "at": time.time(), "kind": "", "text": ""})
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.respawned, [["acme-tui", "fable", OWN]])
        self.assertEqual(watch.seat_read(SEAT)["midturn"],
                         {"boot": watch.boot_id(), "at": NOW, "name": SEAT,
                          "line": watch.MIDTURN_LINE})

    def test_a_seat_its_usage_cut_off_mid_turn_is_told_to_go_on(self):
        # `⇄ Go on now` under a seat out of usage: the turn the refusal ended goes on
        watch.seat_write(SEAT, state="at_prompt", usage_wait={
            "reason": "anthropic out of usage until 2026-10-20 19:20", "until": NOW + 3600,
            "since": NOW - 60, "continue": True})
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.respawned, [["acme-tui", "fable", OWN]])
        self.assertEqual(watch.seat_read(SEAT)["midturn"]["line"], watch.MIDTURN_LINE)
        self.assertIsNone(watch.seat_read(SEAT).get("usage_wait"))

    def test_a_seat_with_a_draft_up_is_refused_and_left_as_it_was(self):
        watch.seat_write(SEAT, state="at_prompt")     # its last reading, from before the draft
        self.pane = capture("claude-draft-pane.txt")
        before = self.record()
        note = self.move("fable")
        self.assertIn(SEAT, note)
        self.assertNotIn("\n", note)
        self.assertEqual((self.respawned, self.record()), ([], before))
        self.pane = ""                           # a capture that failed shows no draft either
        self.assertIn(SEAT, self.move("fable"))
        self.assertEqual((self.respawned, self.record()), ([], before))
        self.seat["exited"] = True               # its harness is gone, and that draft with it
        self.assertEqual(self.move("fable"), "")

    def test_a_redress_while_the_new_harness_comes_up_draws_the_new_model(self):
        self.move("fable")
        self.assertIn(("fable", "redress"), self.bar)
        self.assertEqual({model for model, _ in self.bar}, {"fable"})

    def test_a_launch_that_fails_leaves_the_record_and_the_bar_as_they_were(self):
        self.refused = "tmux refused; the old pane is still running"
        self.assertIn("tmux refused", self.move("fable"))
        self.assertEqual((self.record()["orchestrator"], self.record()["conversation"]),
                         ("opus", OWN))
        self.assertEqual(self.bar[-1][0], "opus")
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def ends_on(self, entry, at):
        """The seat's conversation's last answer: that entry's model, at `at`, as Claude Code
        writes an answer."""
        record = self.record()
        written = claude.transcript_path(record, record["conversation"])
        written.parent.mkdir(parents=True, exist_ok=True)
        with written.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant",
                                 "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(),
                                 "message": {"model": self.cfg["models"][entry]["model"]}}) + "\n")

    def looked(self):
        """Its orchestrator once a look has followed what it last answered."""
        watch.follow_model(self.cfg, SEAT)
        return self.record()["orchestrator"]

    def test_the_old_models_last_answer_does_not_undo_a_move(self):
        self.ends_on("opus", NOW - 60)           # a seat launched before launches were marked
        self.assertEqual(self.looked(), "opus")
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.looked(), "fable")
        self.ends_on("fable", NOW + 60)
        self.assertEqual(self.looked(), "fable")

    def test_an_answer_the_old_harness_writes_as_it_goes_does_not_undo_it(self):
        start, clock = orch._start_harness, Ticking(time.sleep)
        with patch.object(orch, "time", clock), patch.object(
                orch, "_start_harness",
                side_effect=lambda *args, **kw: self.ends_on("opus", clock.time())
                or start(*args, **kw)):
            self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.looked(), "fable")

    def test_a_look_while_the_new_harness_comes_up_waits_for_it(self):
        self.ends_on("opus", NOW - 60)
        seen, start = [], orch._start_harness

        def look():
            with watch.announcing(SEAT):
                seen.append(self.looked())
        meanwhile = threading.Thread(target=look)

        def starting(*args, **kw):
            meanwhile.start()
            meanwhile.join(0.5)                  # held off: it looks once the move is done
            start(*args, **kw)
        with patch.object(orch, "_start_harness", side_effect=starting):
            self.assertEqual(self.move("fable"), "")
        meanwhile.join()
        self.assertEqual((seen, self.record()["orchestrator"]), (["fable"], "fable"))

    def test_back_to_the_old_model_inside_the_seat_after_a_move_is_followed(self):
        self.ends_on("opus", NOW - 60)
        self.assertEqual(self.move("fable"), "")
        self.ends_on("opus", NOW + 60)           # `/model` back to opus before fable answered
        self.assertEqual(self.looked(), "opus")

if __name__ == "__main__":
    unittest.main()

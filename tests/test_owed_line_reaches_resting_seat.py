"""A line written into a resting seat's plan reaches that seat; it is never the owner's to pass on.

The tick wrote a proven switch's line into the plan of a seat whose job was finished and live.
Nothing typed it in, so the seat read `needs you` for two hours with nothing asked, until the
owner came to ask why (20 Oct 2026).  An open line nobody has told a resting seat is ak's to
type, like a run's ending: the seat reads working while it waits, the tick's plan pass
(`watch.tell_plans`) types it once at the seat's quiet prompt, on every harness alike, and only
a stop with the line still open after that is the owner's.  Offline: fake seats, fake tmux,
fake captures and a throwaway HOME.
"""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, plan, watch, worker

NOW = 1_800_000_000
SEAT = "acme-api"
OUTCOME = "acme's switch new_parser is out of the code"
LINE = f"- [ ] {OUTCOME} · check: `false` · acme · written 2026-10-20 10:33"
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
TOLD = (f"Your plan has an open line: {OUTCOME}. `ak plan` shows each with its check. "
        "Decide the next step.")


class OwedLineReachesRestingSeat(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        repo = str(config.CODE / "acme")
        self.seat = {"name": SEAT, "repo": repo, "path": repo, "created": NOW - 86400,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, SEAT, "fable", ["opus"], {"repo": repo, "cwd": repo})
        listed = lambda *_a, **_k: [self.seat]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value=PROMPT))
        self.stack.enter_context(patch.object(worker, "auth_ok",
                                              side_effect=lambda h, seat=False: (True, h)))
        # the seat finished its own job: every line it wrote is proven
        config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")
        self.turn("Stop")
        self.screen = PROMPT

    def turn(self, event, **extra):
        """What the seat's own lifecycle hook writes, then a screen looking at it."""
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": event, "kind": "", "text": "", "at": NOW - 60, **extra}))
        watch.look_at(self.seat, cfg=self.cfg)

    def written(self, line=LINE):
        """What the tick's switch retirement does: an open line appended to the seat's plan."""
        path = config.plan_path(SEAT)
        path.write_text(path.read_text() + line + "\n")

    def decide(self, harness="claude"):
        found = watch.session_state(SEAT, NOW, session=self.seat, cfg=self.cfg,
                                    live=watch.seat_read(SEAT), harness=harness)
        return found["word"], found["reason"]

    def tick(self, takes=True):
        """The tick's plan pass, the seat's screen showing its prompt and a typed line in its
        composer until an Enter it `takes`: the keys the fake tmux was given, in order."""
        sent = []

        def tmux(*args, socket=None, client=False, **_kw):
            if args[0] == "send-keys":
                sent.append(args[-1])
                if "-l" in args:
                    self.screen = PROMPT.replace("❯\xa0\n", f"❯\xa0{args[-1]}\n")
                elif takes:
                    self.screen = PROMPT
            return 0, ""
        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "pane_text", side_effect=lambda *_a: self.screen), \
                patch.object(watch.time, "sleep", lambda _s: None):
            watch.tell_plans(self.cfg, lambda _line: None)
        return sent

    def test_a_line_written_while_it_rests_reads_working_on_every_harness(self):
        self.assertEqual(self.decide()[0], "done")
        self.written()
        harnesses = sorted(path.stem for path in (REPO / "adapters").glob("*.toml"))
        self.assertIn("claude", harnesses)
        for harness in harnesses:
            with self.subTest(harness=harness):
                self.assertEqual(self.decide(harness),
                                 ("working", watch.TELLING_PLAN + OUTCOME))

    def test_the_tick_types_it_once_and_a_stop_with_it_still_open_is_the_owners(self):
        self.written()
        self.assertEqual(self.tick(), [TOLD, "Enter"])
        self.assertEqual(self.tick(), [])                       # once
        self.assertEqual(self.decide(), ("needs you", f"stopped with work open: {OUTCOME}"))
        self.assertIsNone(notify.last(SEAT, include_seen=True))  # typed, nobody paged
        # a line written again is a new line, told in its turn
        self.written(LINE.replace("10:33", "11:40"))
        self.assertEqual(self.decide()[0], "working")
        self.assertEqual(self.tick(), [TOLD, "Enter"])

    def test_several_lines_go_in_as_one(self):
        self.written()
        self.written(LINE.replace(OUTCOME, "acme's switch old_export is out of the code"))
        self.assertEqual(self.tick(), [
            f"Your plan has 2 open lines: {OUTCOME}; acme's switch old_export is out of the "
            "code. `ak plan` shows each with its check. Decide the next step.", "Enter"])

    def test_nothing_is_typed_mid_turn_and_the_line_comes_at_the_next_quiet_prompt(self):
        self.written()
        self.turn("UserPromptSubmit")
        self.assertEqual(self.decide()[0], "working")
        self.assertEqual(self.tick(), [])
        self.turn("Stop")
        self.assertEqual(self.tick(), [TOLD, "Enter"])

    def test_a_question_standing_or_a_turn_the_owner_stopped_gets_nothing(self):
        self.written()
        notify.record(SEAT, "needs", "Which schema should acme use?", time=NOW - 30)
        self.assertEqual(self.decide(), ("needs you", "Which schema should acme use?"))
        self.assertEqual(self.tick(), [])
        config.notify_path(SEAT).unlink()           # answered
        watch.seat_write(SEAT, interrupted=NOW - 30)
        self.assertNotEqual(self.decide()[0], "needs you")
        self.assertEqual(self.tick(), [])

    def test_a_line_its_composer_kept_is_sent_only_while_the_seat_still_reads_told(self):
        self.written()
        self.assertEqual(self.tick(takes=False), [TOLD, "Enter", "Enter"])
        self.assertEqual(self.tick(), ["Enter"])                # nothing changed: it goes
        self.assertEqual(self.tick(), [])                       # and the next pass reads it sent
        self.assertEqual(self.decide(), ("needs you", f"stopped with work open: {OUTCOME}"))
        for change in (
                lambda: notify.record(SEAT, "needs", "Which schema should acme use?",
                                      time=NOW - 30),
                lambda: watch.seat_write(SEAT, interrupted=NOW - 30),
                lambda: config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")):
            with self.subTest(change=change):
                config.notify_path(SEAT).unlink(missing_ok=True)
                config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")
                watch.seat_write(SEAT, interrupted=None, plan_told=None, plan_typing=None)
                self.screen = PROMPT
                self.written()
                self.assertEqual(self.tick(takes=False), [TOLD, "Enter", "Enter"])
                change()
                self.assertNotEqual(self.decide()[0], "working")
                self.assertEqual(self.tick(), [])
        self.assertIsNone(watch.seat_read(SEAT)["plan_typing"])   # its line closed: dropped

    def test_an_esc_the_send_lock_reads_gets_nothing(self):
        self.written()
        config.update_session(SEAT, orchestrator="astra")
        codex = (REPO / "tests/fixtures/codex-prompt-pane.txt").read_text()
        sent = []

        def tmux(*args, socket=None, client=False, **_kw):
            sent.append(args[-1])
            return 0, ""

        def escape(_held):
            """The owner's Esc, as its hook writes it, read in the send lock's own look."""
            config.hook_facts_path(SEAT).write_text(json.dumps(
                {"session": SEAT, "event": "Interrupt", "kind": "", "text": "", "at": NOW}))
            watch.live_state(self.seat, "codex", pane=codex, cfg=self.cfg, now=NOW)
        with patch.object(watch, "seat_model", return_value=("codex", "openai")), \
                patch.object(watch, "pane_text", return_value=codex), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(orch, "rulebook_prepare", side_effect=escape), \
                patch.object(watch.time, "sleep", lambda _s: None):
            self.turn("Stop")
            self.assertEqual(self.decide("codex")[0], "working")
            watch.tell_plans(self.cfg, lambda _line: None)
        self.assertEqual([key for key in sent if key in (TOLD, "Enter")], [])

    def test_a_told_line_that_closed_leaves_the_seats_record(self):
        self.written()
        self.assertEqual(self.tick(), [TOLD, "Enter"])
        self.assertEqual(list(watch.seat_read(SEAT)["plan_told"]), [plan.identity(LINE)])
        config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")
        self.assertEqual(self.tick(), [])
        self.assertEqual(watch.seat_read(SEAT)["plan_told"], {})


if __name__ == "__main__":
    unittest.main()

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
TOLD = ("Your plan has an open line you were not told of. `ak plan` shows each with its check. "
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

    def stopped(self):
        """The owner's Esc on a turn its hook began: Claude runs no hook on it, and records it in
        its transcript (`watch.interrupted_at`)."""
        self.stack.enter_context(patch.object(watch, "interrupted_at", return_value=NOW - 30))
        self.turn("UserPromptSubmit")

    def written(self, line=LINE):
        """What the tick's switch retirement does: an open line appended to the seat's plan."""
        path = config.plan_path(SEAT)
        path.write_text(path.read_text() + line + "\n")

    def decide(self, harness="claude"):
        """The seat's word as a screen reads it: a look at the seat, then the decision."""
        watch.look_at(self.seat, cfg=self.cfg)
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
        other = LINE.replace(OUTCOME, "acme's switch old_export is out of the code")
        self.written()
        self.written(other)
        self.assertEqual(self.tick(), [TOLD, "Enter"])
        self.assertEqual(set(watch.seat_read(SEAT)["plan_told"]),
                         {plan.identity(LINE), plan.identity(other)})

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
        self.stopped()
        self.assertNotEqual(self.decide()[0], "needs you")
        self.assertEqual(self.tick(), [])

    def test_a_line_its_composer_kept_goes_only_while_the_seat_still_reads_told(self):
        self.written()
        self.assertEqual(self.tick(takes=False), [TOLD, "Enter", "Enter"])
        self.assertEqual(self.tick(), ["Enter"])                # nothing changed: it goes
        self.assertEqual(self.tick(), [])                       # and the next pass reads it sent
        self.assertEqual(self.decide(), ("needs you", f"stopped with work open: {OUTCOME}"))
        for change in (
                lambda: notify.record(SEAT, "needs", "Which schema should acme use?",
                                      time=NOW - 30),
                self.stopped,
                lambda: config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")):
            with self.subTest(change=change):
                config.notify_path(SEAT).unlink(missing_ok=True)
                config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")
                watch.seat_write(SEAT, plan_told=None, plan_typing=None)
                self.turn("Stop")
                self.screen = PROMPT
                self.written()
                self.assertEqual(self.tick(takes=False), [TOLD, "Enter", "Enter"])
                change()
                self.assertNotEqual(self.decide()[0], "working")
                self.assertEqual(self.tick(), [])
        # its line closed and another came: the line kept names no line, so it goes for that one
        written = LINE.replace("10:33", "11:40")
        self.written(written)
        self.assertEqual(self.tick(), ["Enter"])
        for _ in range(2):
            self.tick()
        self.assertIn(plan.identity(written), watch.seat_read(SEAT)["plan_told"])

    def keys_after_esc(self, when):
        """The plan pass on a Codex seat whose owner presses Esc, as its hook writes it, when the
        send lock is taken, as the text goes in, or while the line waits in the composer: the
        keys ak sent after it."""
        self.written()
        config.update_session(SEAT, orchestrator="astra")
        codex = (REPO / "tests/fixtures/codex-prompt-pane.txt").read_text()
        screen, sent, takes = [codex], [], [when != "kept"]

        def esc(*_a):
            config.hook_facts_path(SEAT).write_text(json.dumps(
                {"session": SEAT, "event": "Interrupt", "kind": "", "text": "", "at": NOW}))
            sent.clear()

        def tmux(*args, socket=None, client=False, **_kw):
            if args[0] == "send-keys":
                sent.append(args[-1])
                if "-l" in args:
                    screen[0] = codex.replace("› Ask Codex to do anything\n", f"› {args[-1]}\n")
                    if when == "text":
                        esc()
                elif takes[0]:
                    screen[0] = codex
            return 0, ""
        with patch.object(watch, "seat_model", return_value=("codex", "openai")), \
                patch.object(watch, "pane_text", side_effect=lambda *_a: screen[0]), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(orch, "rulebook_prepare",
                             side_effect=esc if when == "lock" else lambda _held: None), \
                patch.object(watch.time, "sleep", lambda _s: None):
            self.turn("Stop")
            self.assertEqual(self.decide("codex")[0], "working")
            watch.tell_plans(self.cfg, lambda _line: None)
            if when == "kept":
                self.assertEqual(sent, [TOLD, "Enter", "Enter"])
                esc()
                takes[0] = True
                watch.tell_plans(self.cfg, lambda _line: None)
        return sent

    def test_no_key_follows_an_esc_as_the_send_lock_is_taken(self):
        self.assertEqual(self.keys_after_esc("lock"), [])

    def test_no_enter_follows_an_esc_as_the_text_goes_in(self):
        self.assertEqual(self.keys_after_esc("text"), [])

    def test_no_enter_follows_an_esc_while_the_line_waits_in_the_composer(self):
        self.assertEqual(self.keys_after_esc("kept"), [])

    def test_a_told_line_that_closed_leaves_the_seats_record(self):
        self.written()
        self.assertEqual(self.tick(), [TOLD, "Enter"])
        self.assertEqual(list(watch.seat_read(SEAT)["plan_told"]), [plan.identity(LINE)])
        config.plan_path(SEAT).write_text("- [x] The parser reads both schemas\n")
        self.assertEqual(self.tick(), [])
        self.assertEqual(watch.seat_read(SEAT)["plan_told"], {})


if __name__ == "__main__":
    unittest.main()

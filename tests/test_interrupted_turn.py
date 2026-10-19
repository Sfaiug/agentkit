"""A turn the owner interrupted reads at its prompt, though its harness never reported it ending.

Claude Code 2.1.291 sends no Stop and no idle_prompt after an Esc.  The conversation's own record
says so: it ends in `[Request interrupted by user]`, and the next prompt is written there before
its hook runs.  An Esc before any answer records nothing a turn not yet answered lacks (2.1.292:
the prompt, its attachments, `last-prompt`, then nothing) and runs no hook, but puts the prompt
back in the composer word for word: that is the owner's draft again.  Once they edit or
empty it, the seat reads `working` until their next prompt: only the prompt put back whole
tells an Esc from a turn still thinking while the owner types.  hooks/seat-state.sh runs as
the harness runs it; the records follow the shape of real ones, with invented names.  Codex and
Muse report an Esc by a hook of their own, which their manifests mark `interrupt`.
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, harness, orch, watch
from agentkit.harness import claude

SEAT = "fix-api"
CONVERSATION = "3f0c2a5e-0000-4000-8000-000000000001"
FIX = REPO / "tests/fixtures"
# real captures: right after an Esc, and once the next prompt runs
INTERRUPTED = (FIX / "claude-interrupted-pane.txt").read_text(encoding="utf-8")
NEXT_TURN = (FIX / "claude-after-interrupt-next-turn-pane.txt").read_text(encoding="utf-8")
DRAFT = (FIX / "claude-multiline-draft-pane.txt").read_text(encoding="utf-8")  # the owner's draft
# a real 2.1.292 capture of a renamed seat: Esc before any answer put the prompt back
CANCELLED = (FIX / "claude-cancelled-before-any-answer-pane.txt").read_text(encoding="utf-8")
INTERRUPT, TOOL_INTERRUPT = claude.INTERRUPTS
OWED = "- [ ] the acme tests pass · check: `false` · acme · written 2026-10-14 09:00\n"


class InterruptedTurn(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": CONVERSATION, "id_source": harness.LAUNCHER})
        self.transcript = claude.transcript_path(config.session_records()[SEAT], CONVERSATION)
        self.transcript.parent.mkdir(parents=True, exist_ok=True)

    def said(self, role, at, text):
        """One message of the conversation's record, as Claude Code writes it."""
        stamp = datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": role, "timestamp": stamp.replace("+00:00", "Z"),
                                 "message": {"role": role,
                                             "content": [{"type": "text", "text": text}]}}) + "\n")

    def prompt(self, text, publish=True):
        """The owner submits a prompt: Claude writes it down, then runs hooks/seat-state.sh."""
        hook = self.root / ".agentkit/state" / f"hook-{SEAT}.json"
        done = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text}),
            env={"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        fact = json.loads(hook.read_text())
        self.said("user", fact["at"] - 0.04, text)
        if publish:
            self.publish(fact)
        return fact

    def publish(self, fact):
        """The hook's record where this sandbox's watch reads it."""
        config.hook_facts_path(SEAT).write_text(json.dumps(fact))

    def looked(self, pane=INTERRUPTED, records=()):
        with patch.object(watch, "pane_text", return_value=pane):
            free = watch.at_prompt({"name": SEAT}, cfg=self.cfg)
        live = watch.live_state({"name": SEAT}, "claude", pane=pane, cfg=self.cfg)
        word = watch.session_state(SEAT, 10000, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=list(records), live=live,
                                   harness="claude",
                                   auth_out={}, gh_out={}, token_out={}, previous={})["word"]
        return word, free

    def handed_back(self, capture=lambda: INTERRUPTED):
        """The hand-back typed at that screen, its line in the composer until its Enter takes
        it: the keys it got."""
        self.keys, typed = [], []

        def look(_session):
            screen = capture()
            if not typed:
                return screen
            return screen.replace("\u276f\u00a0\n", f"\u276f\u00a0{typed[-1]}\n")

        def keys(*args, **_kw):
            if args[0] != "send-keys":
                return 1, "no tty in this screen fixture"
            self.keys.append(args)
            if args[-2] == "-l":
                typed.append(args[-1])
            elif args[-1] == "Enter":
                typed.clear()
            return 0, ""

        with patch.object(watch, "pane_text", side_effect=look), \
                patch.object(orch, "tmux_out", side_effect=keys), \
                patch.object(watch, "KEY_GAP", 0):
            watch.type_at_prompt({"name": SEAT}, "The acme tests passed.", lambda _: None,
                                 cfg=self.cfg)
        return [key[-1] for key in self.keys]

    def test_an_interrupted_turn_is_at_its_prompt_and_free_to_type_into(self):
        fact = self.prompt("Run the acme tests.")
        self.said("assistant", fact["at"] + 2, "Running them now.")
        self.assertEqual(self.looked(), ("working", False))
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.assertEqual(self.looked(), ("idle", True))
        self.assertEqual(self.handed_back(), ["The acme tests passed.", "Enter"])

    def test_a_turn_the_owner_stopped_rests_whatever_its_plan_still_owes(self):
        """The owner's rule (14 Oct 2026): Esc reads idle.  The owner is in the seat and stopped
        it, so the line its plan owes is no `needs you`; their next prompt runs again."""
        config.plan_path(SEAT).write_text(OWED)
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.assertEqual(self.looked(), ("idle", True))
        self.prompt("Now the lint too.")
        self.assertEqual(self.looked(NEXT_TURN)[0], "working")

    def test_esc_waives_only_the_plan_not_a_kept_question(self):
        """review of #998 round 1: that is the owner's whoever ended the turn."""
        config.plan_path(SEAT).write_text(OWED)
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.assertEqual(self.looked()[0], "idle")
        watch.keep(SEAT, "Which schema?")
        self.assertEqual(self.looked()[0], "needs you")

    def test_a_turn_stopped_by_a_harness_hook_of_its_own_rests_too(self):
        """review of #998 rounds 1 and 2: Codex and Muse send `Interrupt`, which no record needs
        to say, and Muse has no prompt hook: an Esc after an earlier Stop is news all the same."""
        config.plan_path(SEAT).write_text(OWED)
        (self.root / ".agentkit").mkdir()
        (self.root / ".agentkit/state").symlink_to(config.STATE)
        env = {"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": SEAT,
               "AK_RUN_ROLE": "orchestrator", "IDLE_COMPACT_STATE": ""}
        for name, model, fixture in (("codex", "astra", "codex-prompt-pane.txt"),
                                     ("muse", "spark", "muse-question-escaped-pane.txt")):
            with self.subTest(harness=name):
                config.save_session(self.cfg, SEAT, model, ["astra"], {"cwd": str(self.root)})
                pane = (FIX / fixture).read_text(encoding="utf-8")

                def word(event):
                    subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], text=True,
                                   input=json.dumps({"hook_event_name": event}), env=env,
                                   timeout=20, check=True)
                    live = watch.live_state({"name": SEAT}, name, pane=pane, cfg=self.cfg)
                    return watch.session_state(
                        SEAT, 10000, session={"name": SEAT, "attached": True}, cfg=self.cfg,
                        records=[], live=live, harness=name, auth_out={}, gh_out={},
                        token_out={}, previous={})["word"]
                self.assertEqual(word("Stop"), "needs you")
                self.assertEqual(word("Interrupt"), "idle")

    def test_the_tick_types_nothing_into_a_muse_turn_the_owner_stopped(self):
        """Muse has no end-of-turn hook, so the tick types `continue` at a stop its plan still
        owes for: never at an Esc, which rests until the owner's next prompt."""
        config.save_session(self.cfg, SEAT, "spark", ["astra"], {"cwd": str(self.root)})
        config.plan_path(SEAT).write_text(OWED)
        pane = (FIX / "muse-question-escaped-pane.txt").read_text(encoding="utf-8")
        for event, keys in (("Interrupt", []), ("Stop", ["continue"])):
            with self.subTest(event=event):
                fact = {"event": event, "at": 9000}
                live = watch.classify("muse", watch.pane_tail(pane), fact, None, {}, 10000)
                watch.seat_write(SEAT, **live, turn_began=8000, stop_said_at=9000)
                with patch.object(watch, "pane_text", return_value=pane), \
                        patch.object(watch, "hook_facts", return_value=fact), \
                        patch.object(watch, "type_into", return_value=True) as typed:
                    watch.stop_nudge({"name": SEAT}, "muse", pane, None, [], False,
                                     lambda _: None)
                self.assertEqual([call.args[1] for call in typed.call_args_list], keys)

    def test_a_turn_interrupted_in_a_tool_call_is_at_its_prompt_too(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, TOOL_INTERRUPT)
        self.assertEqual(self.looked(), ("idle", True))

    def test_the_next_prompt_after_an_interrupt_is_a_turn_running(self):
        """Written down before its hook runs, it is the record's last message at once: the turn
        is its own, published or not, whatever the screen still shows."""
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.prompt("Run them in the foreground.", publish=False)
        self.assertEqual(self.looked(), ("working", False))     # its screen not drawn yet
        self.publish(json.loads((self.root / f".agentkit/state/hook-{SEAT}.json").read_text()))
        self.assertEqual(self.looked(NEXT_TURN), ("working", False))
        self.assertEqual(self.handed_back(), [])

    def test_a_prompt_whose_hook_lands_while_the_screen_is_read_gets_no_keys(self):
        """review 20261005-0749, rounds 1 and 2: the next prompt's hook publishes during a
        capture, at the first look or the last under the send lock -- here before its own
        message is written down, so that only the hook says the turn is new."""
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        newer = dict(fact, at=fact["at"] + 10)
        for look in range(1, 4):
            with self.subTest(look=look):
                self.publish(fact)
                looks = []

                def capture():
                    looks.append(look)
                    if len(looks) == look:
                        self.publish(newer)
                    return INTERRUPTED
                self.assertEqual(self.handed_back(capture), [])

    def test_a_prompt_whose_hook_lands_while_the_record_is_read_is_a_turn_running(self):
        """review 20261005-0749 round 3: the record was read up to an end fixed before the next
        prompt went in, and its hook published before the read finished."""
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        read, looks = watch.interrupted_at, []
        with patch.object(watch, "interrupted_at",
                          side_effect=lambda *a: looks.append(len(self.keys)) or read(*a)):
            self.assertEqual(self.handed_back(), ["The acme tests passed.", "Enter"])
        for look in range(1, looks.count(0) + 1):     # every read before the first key
            with self.subTest(look=look):
                self.publish(fact)
                reads = []

                def racing(harness, name):
                    reads.append(read(harness, name))
                    if len(reads) == look:
                        self.publish(dict(fact, at=fact["at"] + 10))
                    return reads[-1]
                with patch.object(watch, "interrupted_at", side_effect=racing):
                    self.assertEqual(self.handed_back(), [])

    def test_a_turn_interrupted_after_its_question_was_answered_is_at_its_prompt(self):
        """review 20261005-0749 round 3: the last hook is the question, answered, and no other
        hook follows until the next prompt."""
        fact = self.prompt("Run the acme tests.")
        for kind in ("permission_prompt", "worker_permission_prompt", "agent_needs_input"):
            with self.subTest(kind=kind):
                self.publish({"event": "Notification", "kind": kind, "at": fact["at"] + 1,
                              "text": "Claude needs your permission"})
                self.said("user", fact["at"] + 3, INTERRUPT)
                self.assertEqual(self.looked(), ("idle", True))

    def test_a_draft_typed_after_an_interrupt_is_the_owners_and_closed_to_typing(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.assertEqual(self.looked(DRAFT), ("idle", False))
        self.assertEqual(self.handed_back(lambda: DRAFT), [])

    def test_a_turn_cancelled_before_any_answer_is_the_owners_draft_again(self):
        """Esc before any answer: Claude records nothing and sends no hook, so the record is a
        turn not yet answered; but the prompt is back in the composer word for word, which a
        turn that runs never leaves (review 20261006-2254 round 1)."""
        fact = self.prompt("Run the acme tests.")
        self.assertEqual(self.looked(CANCELLED), ("idle", False))        # its draft again
        self.assertEqual(self.handed_back(lambda: CANCELLED), [])         # and never typed onto
        # edited by a word, it is what a turn still thinking with the owner typing shows
        edited = CANCELLED.replace("Run the acme tests.\n", "Run the acme tests twice.\n")
        self.assertNotEqual(edited, CANCELLED)
        self.assertEqual(self.looked(edited), ("working", False))
        self.said("assistant", fact["at"] + 2, "Running them now.")      # once answered: no cancel
        self.assertEqual(self.looked(CANCELLED), ("working", False))

    def test_a_seat_whose_record_cannot_be_read_reads_as_its_hooks_say(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.transcript.unlink()
        self.transcript.mkdir()     # there, and no record to read
        self.assertEqual(self.looked(), ("working", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)

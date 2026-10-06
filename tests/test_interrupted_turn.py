"""A turn the owner interrupted reads at its prompt, though its harness never reported it ending.

Claude Code 2.1.291 sends no Stop and no idle_prompt after an Esc.  The conversation's own record
says so: it ends in `[Request interrupted by user]`, and the next prompt is written there before
its hook runs.  An Esc before any answer is not read here: the record of it is the record of a
turn not yet answered (2.1.292: the prompt, its attachments, `last-prompt`, then nothing), and
no hook runs, so that seat reads `working` until its next prompt.  hooks/seat-state.sh runs as
the harness runs it; the records follow the shape of real ones, with invented names.
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, harness, orch, watch
from agentkit.harness import claude

SEAT = "fix-api"
CONVERSATION = "3f0c2a5e-0000-4000-8000-000000000001"
FIX = REPO / "tests/fixtures"
# real captures: right after an Esc, and once the next prompt runs
INTERRUPTED = (FIX / "claude-interrupted-pane.txt").read_text(encoding="utf-8")
NEXT_TURN = (FIX / "claude-after-interrupt-next-turn-pane.txt").read_text(encoding="utf-8")
DRAFT = (FIX / "claude-multiline-draft-pane.txt").read_text(encoding="utf-8")  # the owner's draft
INTERRUPT, TOOL_INTERRUPT = claude.INTERRUPTS


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

    def looked(self, pane=INTERRUPTED):
        with patch.object(watch, "pane_text", return_value=pane):
            free = watch.at_prompt({"name": SEAT}, cfg=self.cfg)
        live = watch.live_state({"name": SEAT}, "claude", pane=pane, cfg=self.cfg)
        word = watch.session_state(SEAT, 10000, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=[], live=live, harness="claude",
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
        self.assertEqual(self.looked(), ("needs you", True))
        self.assertEqual(self.handed_back(), ["The acme tests passed.", "Enter"])

    def test_a_turn_interrupted_in_a_tool_call_is_at_its_prompt_too(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, TOOL_INTERRUPT)
        self.assertEqual(self.looked(), ("needs you", True))

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
                self.assertEqual(self.looked(), ("needs you", True))

    def test_a_draft_typed_after_an_interrupt_is_the_owners_and_closed_to_typing(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.assertEqual(self.looked(DRAFT), ("needs you", False))
        self.assertEqual(self.handed_back(lambda: DRAFT), [])

    def test_a_seat_whose_record_cannot_be_read_reads_as_its_hooks_say(self):
        fact = self.prompt("Run the acme tests.")
        self.said("user", fact["at"] + 3, INTERRUPT)
        self.transcript.unlink()
        self.transcript.mkdir()     # there, and no record to read
        self.assertEqual(self.looked(), ("working", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)

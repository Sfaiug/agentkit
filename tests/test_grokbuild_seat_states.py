"""A Grok Build 1.0.46 seat reads as what it is doing, off a live sweep's own captures.

Each pane is a real seat's capture (`capture-pane -p -e -J`, colours kept), cut to the rows
`watch.pane_tail` reads and renamed; each payload is one grok handed its hooks there, cut to
the fields hooks/seat-state.sh reads.  The payloads go through that hook as on a seat, and
what it writes down is the fact `watch.classify` reads beside the pane.
"""

import json
import subprocess
import unittest

from test_grokbuild import FIX, NOW, REPO, GrokSandbox
from agentkit import config, watch

PROMPT = {"hook_event_name": "UserPromptSubmit",
          "prompt": "Run `sleep 40` with your shell tool, then reply OK."}
QUESTION = {"hook_event_name": "Notification", "notificationType": "elicitation_dialog",
            "message": "User question requested"}
ANSWERED = {"hook_event_name": "PostToolUse", "toolName": "ask_user_question"}
PERMISSION = {"hook_event_name": "Notification", "notificationType": "permission_prompt",
              "message": "Tool permission requested"}
CANCELLED = {"hook_event_name": "StopCancelled", "reason": "user_interrupt"}
# documented, not provoked: an API error ends the turn with this instead of its Stop
FAILED = {"hook_event_name": "StopFailure", "error": "server_error"}
IDLE = {"hook_event_name": "Notification", "notificationType": "idle_prompt",
        "message": "Waiting for your next prompt"}


class SeatStates(GrokSandbox):
    def setUp(self):
        super().setUp()
        config.save_session(config.load(), "atoll", "grok", ["grok"])
        for name in ("TMUX", "TMUX_PANE"):    # the hook's look never reaches a real pane
            self.env.pop(name, None)

    def heard(self, *payloads):
        """The fact hooks/seat-state.sh has written down once it has heard those, in order."""
        for payload in payloads:
            proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                                  input=json.dumps(payload), capture_output=True, text=True,
                                  env=self.env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads((self.state / "hook-atoll.json").read_text())

    def seen(self, name, fact):
        """(screen_state, classify) of that capture, beside that fact."""
        tail = watch.pane_tail((FIX / f"grokbuild-{name}-pane.txt").read_text(encoding="utf-8"))
        return (watch.screen_state("grokbuild", tail),
                watch.classify("grokbuild", tail, fact, None, {}, NOW))

    def test_a_permission_card_is_asking(self):
        # its Ctrl+c:cancel hint read as a turn running, at every width that draws it
        asked = self.heard(PROMPT, PERMISSION)
        for name in ("permission", "permission-parked", "permission-narrow"):
            with self.subTest(name=name):
                screen, found = self.seen(name, asked)
                self.assertEqual(screen[:2], ("asking", "asking.permission"))
                self.assertEqual(found["state"], "asking")

    def test_a_question_card_is_asking_until_answered(self):
        asked = self.heard(PROMPT, QUESTION)
        for name in ("question", "question-parked"):
            with self.subTest(name=name):
                screen, found = self.seen(name, asked)
                self.assertEqual(screen[:2], ("asking", "asking.question"))
                self.assertEqual((found["state"], found["authority"]), ("asking", "hook"))
        # the tool's own end, 0.15 s after the answer, says the turn runs on
        answered = self.heard(ANSWERED)
        self.assertEqual((answered["event"], answered["kind"]), ("PostToolUse", "ask_user_question"))
        found = self.seen("question-answered", answered)[1]
        self.assertEqual((found["state"], found["authority"]), ("working", "hook"))

    def test_ctrl_c_and_an_api_error_end_the_turn(self):
        found = self.seen("interrupted", self.heard(PROMPT, CANCELLED))[1]
        self.assertEqual((found["state"], found["hooked"]), ("at_prompt", "at_prompt"))
        self.assertEqual(watch.hook_state("grokbuild", self.heard(PROMPT, FAILED))[0], "at_prompt")

    def test_compacting_is_a_running_turn(self):
        # /compact fires no prompt and no Stop: the last fact is the settled prompt before it
        screen, found = self.seen("compacting", self.heard(IDLE))
        self.assertEqual(screen[:2], ("working", "working.turn"))
        self.assertEqual(found["state"], "working")

    def test_a_stop_on_background_work_is_a_wait(self):
        # as hooks/orchestrator-stop.sh writes it down once it reads grok's `backgroundTasks`;
        # the composer stays open, so the screen reads the prompt and the hook the wait
        stop = {"session": "atoll", "event": "Stop", "kind": "background", "text": "", "at": NOW}
        found = self.seen("background", stop)[1]
        self.assertEqual((found["hooked"], found["hooked_event"]), ("working", "Stop/background"))
        for kind, state in (("held", "working"), ("", "at_prompt")):
            with self.subTest(kind=kind):
                self.assertEqual(watch.hook_state("grokbuild", dict(stop, kind=kind))[0], state)

    def test_the_draft_is_the_composer_s_own_text(self):
        # under the first Esc's own key hint, and under a slash command's dropdown
        for name, draft in (("esc-clear", "please remember the word pineapple"),
                            ("slash", "/model")):
            with self.subTest(name=name):
                self.assertEqual(self.seen(name, {})[0], ("draft", "prompt.draft", draft))

    def test_a_suggestion_of_the_last_prompt_is_an_empty_composer_and_no_part_of_a_draft(self):
        # an ending's line waited behind it as behind a draft; what is typed over its start is one
        for name, state, draft in (("suggestion", "at_prompt", ""),
                                   ("suggestion-typed", "draft", "Replywith")):
            with self.subTest(name=name):
                pane = (FIX / f"grokbuild-{name}-pane.txt").read_text(encoding="utf-8")
                self.assertEqual((self.seen(name, {})[1]["state"],
                                  watch.composer_draft("grokbuild", pane)), (state, draft))


if __name__ == "__main__":
    unittest.main()

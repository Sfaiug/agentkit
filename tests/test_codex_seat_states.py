"""A Codex seat's question, approval, draft and pickers read as they are.

Each case is a pane a live sweep of Codex 0.160.1 seats captured -- the tail ak reads of it,
names invented -- read beside the hook events Codex fired for it, as the hooks a seat's launch
installs for them write them down: hooks/seat-state.sh, and a question going up and a call's
end through `codex-seat.py ask` and `answered`, against a temporary HOME.
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, watch
from agentkit.harness import codex

SEAT = "fix-api"
HOOK = {"PreToolUse": [sys.executable, str(REPO / "tools/codex-seat.py"), "ask"],
        "PostToolUse": [sys.executable, str(REPO / "tools/codex-seat.py"), "answered"]}


def tail(name, *swap):
    """The tail ak reads of that capture, with one piece of its text swapped where given."""
    text = (REPO / f"tests/fixtures/codex-{name}-pane.txt").read_text()
    return watch.pane_tail(text.replace(*swap) if swap else text)


class CodexSeatStates(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "astra", ["astra"], {"cwd": str(self.root)})
        (self.root / ".agentkit").mkdir()
        (self.root / ".agentkit/state").symlink_to(config.STATE)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

    def hook(self, event, **payload):
        """That event through the hook Codex runs for it; the seat's fact after it."""
        subprocess.run(HOOK.get(event, ["bash", str(REPO / "hooks/seat-state.sh")]),
                       input=json.dumps({"hook_event_name": event, **payload}),
                       env=self.env, text=True, timeout=20, check=True)
        return watch.hook_facts(SEAT)

    def read(self, name):
        """(state, who said it, why) of that pane beside the seat's fact."""
        found = watch.classify("codex", tail(name), watch.hook_facts(SEAT), None, {}, 10000)
        return found["state"], found["authority"], found["rule"]

    def screen(self, name, *swap):
        return watch.screen_state("codex", tail(name, *swap))[:2]

    def test_a_plan_mode_question_asks_until_it_is_answered(self):
        self.hook("UserPromptSubmit", prompt="Ask me which color.")
        # its dialog's hint says `esc to interrupt`, at any width
        self.hook("PreToolUse", tool_name="request_user_input", tool_use_id="call_1")
        for name in ("question-up", "question-up-narrow"):
            self.assertEqual(self.screen(name), ("asking", "asking.question"))
            self.assertEqual(self.read(name), ("asking", "hook", "PreToolUse/request_user_input"))
        # its hint's words in a draft or a thread's title are no dialog
        words = "Please document enter to submit answer"
        for name, said, reading in (("draft", "Fix the login redirect", ("draft", "prompt.draft")),
                                    ("approved", "Run sleep and list animals",
                                     ("working", "working.interrupt")),
                                    ("sub-agent-done", "Run sleep and list animals",
                                     ("at_prompt", "prompt.suggestion"))):
            self.assertEqual(self.screen(name, said, words), reading, name)
        # the call goes through to the dialog: only the question that waits for nobody is ak's
        self.assertIsNone(codex.ask({"hook_event_name": "PreToolUse",
                                     "tool_name": "request_user_input"}))
        self.assertIsNone(watch.hook_state("codex", {"event": "PreToolUse", "at": 1.0,
                                                     "kind": codex.QUESTION_TOOL})[0])
        fact = self.hook("PostToolUse", tool_name="request_user_input", tool_use_id="call_1",
                         tool_response={"answers": {"color": {"answers": ["Red"]}}})
        self.assertEqual(watch.hook_state("codex", fact)[:2],
                         ("working", "PostToolUse/request_user_input"))

    def test_an_approved_call_runs_on_at_once(self):
        self.hook("UserPromptSubmit", prompt="Touch a file outside the workspace.")
        self.hook("PermissionRequest", tool_name="Bash", tool_use_id="exec-1")
        self.hook("PostToolUse", tool_name="Bash", tool_use_id="exec-1")
        self.assertEqual(self.read("approved"), ("working", "hook", "PostToolUse/Bash"))
        # any other call's end says nothing the seat's fact lacks
        running = self.hook("PostToolUse", tool_name="Bash", tool_use_id="exec-2")
        self.assertEqual(self.hook("PostToolUse", tool_name="Bash", tool_use_id="exec-3"), running)
        # ... nor brings back a turn the owner's Esc ended, as a shell left running ends later
        ended = self.hook("Interrupt", turn_id="turn-1")
        self.assertEqual(self.hook("PostToolUse", tool_name="Bash", turn_id="turn-1"), ended)

    def test_a_sub_agent_leaves_the_seat_at_its_prompt(self):
        self.hook("UserPromptSubmit", prompt="Spawn one sub-agent, then end your turn.")
        stop = self.hook("Stop")
        for event in ("SubagentStart", "SubagentStop"):
            self.assertIsNone(watch.hook_state("codex", {"event": event, "at": 1.0})[0])
        # the sub-agent's own calls go through the seat's hooks after the seat's Stop
        self.assertEqual(self.hook("PostToolUse", tool_name="Bash", agent_id="agent-1",
                                   agent_type="worker"), stop)
        self.assertEqual(self.read("sub-agent-done"), ("at_prompt", "hook", "Stop"))

    def test_a_draft_past_its_prompt_row_is_one_however_its_rows_are_drawn(self):
        self.hook("Stop")
        pane = (REPO / "tests/fixtures/codex-draft-two-lines-pane.txt").read_text()
        warning = (REPO / "tests/fixtures/codex-draft-warning-pane.txt").read_text().splitlines()[-1]
        for drawn in (pane.replace("  line two", "    line two"),
                      pane.replace("  line two", "  Red · Blue"), pane + warning + "\n"):
            found = watch.classify("codex", watch.pane_tail(drawn), {"event": "Stop", "at": 1.0},
                                   None, {}, 2.0)
            self.assertEqual(found["state"], "draft", drawn[-200:])
        # a row of it opening on a prompt mark is its text, never a composer of its own
        for mark in "›❯⟩":
            drawn = pane.replace("  line two", f"  {mark} quoted\n  line two")
            self.assertEqual(watch.screen_state("codex", watch.pane_tail(drawn)),
                             ("draft", "prompt.draft", f"line one of draft {mark} quoted line two"))
        # a placeholder wrapped onto a second row is still no draft: its faint carries on
        empty = (REPO / "tests/fixtures/codex-resumed-warning-pane.txt").read_text().replace(
            "Ask Codex to do anything", "Ask Codex to do\n  anything")
        for drawn in (empty, "\n".join(empty.splitlines()[:-1] + ["  ? for shortcuts"]) + "\n"):
            found = watch.classify("codex", watch.pane_tail(drawn), {"event": "Stop", "at": 1.0},
                                   None, {}, 2.0)
            self.assertEqual(found["state"], "at_prompt", drawn[-200:])

    def test_what_the_owner_has_in_hand_is_a_draft(self):
        self.hook("Stop")
        # a draft past its prompt row, read from that row down, a one-row one over a warning,
        # an open picker
        for name, rule in (("draft-wrapped", "prompt.draft"), ("draft-two-lines", "prompt.draft"),
                           ("draft-warning", "prompt.draft"), ("model-picker", "draft.picker"),
                           ("effort-picker", "draft.picker")):
            self.assertEqual(self.read(name), ("draft", "screen", rule), name)
        # and says all of it the composer shows, never only its last row
        for name, words in (("draft-two-lines", "line one of draft line two"),
                            ("draft-wrapped", "this is a draft I never sent and it is long enough"
                             " to wrap across the narrow composer line of the pane so that it takes"
                             " two rows")):
            self.assertEqual(watch.screen_state("codex", tail(name))[2], words, name)
        self.assertEqual(self.screen("resumed-warning"), ("at_prompt", "prompt.suggestion"))

    def test_a_draft_cropped_above_the_tail_keeps_its_visible_rows(self):
        for name in ("tall-line", "tall-line-and-owner-words"):
            original = (REPO / f"tests/fixtures/codex-{name}-pane.txt").read_text()
            for edit in (None, "    def login(): pass", "  owner · draft"):
                with self.subTest(name=name, edit=edit):
                    rows = tail(name).splitlines()
                    if edit:
                        rows[2] = edit
                    pane = "\n".join(rows)
                    capture = "\n".join(watch._content_rows(original)[:-watch.PANE_LINES] + rows)
                    words = " ".join(watch.strip_sgr(row).strip() for row in rows[:-1])
                    found = watch.classify("codex", pane, None, None, {}, 10000)
                    self.assertEqual((found["state"], found["rule"], found["evidence"]),
                                     ("draft", "draft.rows", words[:160]))
                    # Display and pending delivery read the same rows, including owner edits.
                    with patch.object(watch, "pane_text", return_value=capture), \
                            patch.object(watch, "seat_model", return_value=("codex", "openai")):
                        self.assertEqual(watch.composer_holds(SEAT, {}, words, self.cfg), "line")
                        self.assertEqual(watch.composer_holds(SEAT, {}, words, self.cfg,
                                                              exact=True), "other")
                    # A short tail without a prompt cannot establish a cropped composer.
                    self.assertEqual(watch.screen_state("codex", "\n".join(rows[1:]))[2],
                                     watch.strip_sgr(rows[-2]).strip())

    def test_the_hook_review_asks(self):
        self.assertEqual(self.read("hooks-review-0160"), ("asking", "screen", "asking.chooser"))


if __name__ == "__main__":
    unittest.main()

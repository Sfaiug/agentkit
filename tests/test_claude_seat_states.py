"""Claude Code 2.1.292's dialogs are heard the moment they open and close, and its spinner,
compaction and mode footers read as what the seat is doing.

A live sweep of 2.1.292 seats heard a question, a plan approval and a tool's permission prompt
only through the notice Claude fires six seconds after the dialog, an answer through nothing,
and read `/compact` as a seat waiting for its owner.  On the screen, a narrow pane, a draft
typed during a turn and every mode but bypass hid the turn or the prompt, and a turn whose Stop
hooks were still running read as one in flight.  Each case here is the sweep's own capture
(tests/fixtures/README.md) and the payload its hooks recorded, replayed through the hook script
a seat runs, `watch.hook_state`, `watch.screen_state` and `watch.classify`.
"""
from datetime import datetime
import json
import os
import subprocess
import unittest

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, watch

SEAT = "fix-api"
FIX = REPO / "tests/fixtures"

# What 2.1.292 handed its hooks in the sweep, cut to the fields ak reads.
QUESTION = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{
    "question": "Which colour do you prefer?", "header": "Colour", "multiSelect": False,
    "options": [{"label": "Red", "description": "The colour red"},
                {"label": "Blue", "description": "The colour blue"}]}]}}
ANSWERED = {**QUESTION, "tool_input": {**QUESTION["tool_input"],
                                       "answers": {"Which colour do you prefer?": "Red"}}}
PLAN = {"tool_name": "ExitPlanMode", "tool_input": {
    "plan": "# Plan: Create hello.txt\n", "planFilePath": "/home/acme/.claude/plans/acme-fix-api.md"}}
WRITE = {"tool_name": "Write",
         "tool_input": {"file_path": "/home/acme/code/fix-api/hello.txt", "content": "hi"}}
NOTICE = {"notification_type": "permission_prompt", "message": "Claude needs your permission"}


def pane(what):
    return watch.pane_tail((FIX / f"claude-{what}-pane.txt").read_text(encoding="utf-8"))


def read(what, fact):
    found = watch.classify("claude", pane(what), fact, None, {}, (fact.get("at") or 0) + 1)
    return found["state"], found["authority"]


class Heard(Sandbox):
    """The hook script a seat runs, against a temporary HOME holding the seat's record."""

    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        home = self.root / ".agentkit"
        home.mkdir()
        (home / "state").symlink_to(config.STATE)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

    def hook(self, event, **payload):
        done = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], text=True,
                              input=json.dumps({"hook_event_name": event, **payload}),
                              capture_output=True, env=self.env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return watch.hook_facts(SEAT)

    def test_a_question_is_heard_as_it_goes_up_in_its_own_words_and_as_it_is_answered(self):
        self.hook("UserPromptSubmit", prompt="Ask me which colour I prefer.")
        asked = self.hook("PermissionRequest", **QUESTION)
        self.assertEqual((asked["event"], asked["kind"], asked["text"]),
                         ("PermissionRequest", "AskUserQuestion", "Which colour do you prefer?"))
        found = watch.classify("claude", pane("question"), asked, None, {}, asked["at"] + 1)
        self.assertEqual((found["state"], found["authority"], found["evidence"]),
                         ("asking", "hook", "Which colour do you prefer?"))
        # its notice six seconds later says what is already written down
        self.assertEqual(self.hook("Notification", **NOTICE), asked)
        answered = self.hook("PostToolUse", **ANSWERED)
        self.assertEqual(answered["event"], "PostToolUse")
        self.assertEqual(read("working-after-question", answered), ("working", "hook"))

    def test_a_plan_and_a_tool_permission_are_heard_and_read(self):
        prompt = self.hook("UserPromptSubmit", prompt="Plan hello.txt, then write it.")
        # drawn before any hook of its lands, each dialog is on the screen alone
        self.assertEqual(read("plan", prompt), ("asking", "screen"))
        self.assertEqual(read("permission", prompt), ("asking", "screen"))
        planned = self.hook("PermissionRequest", **PLAN)
        self.assertEqual(read("plan", planned), ("asking", "hook"))
        self.assertEqual(read("narrow-working", self.hook("PostToolUse", **PLAN)),
                         ("working", "hook"))
        self.assertEqual(read("permission", self.hook("PermissionRequest", **WRITE)),
                         ("asking", "hook"))

    def test_compact_is_working_until_it_ends(self):
        self.hook("UserPromptSubmit", prompt="Say OK.")
        self.hook("Stop", last_assistant_message="OK")
        began = self.hook("PreCompact", trigger="manual", custom_instructions=None)
        self.assertEqual((began["event"], began["kind"]), ("PreCompact", "manual"))
        self.assertEqual(read("compacting", began), ("working", "hook"))
        ended = self.hook("PostCompact", trigger="manual", compact_summary="Said OK.")
        self.assertEqual((ended["event"], ended["kind"]), ("PostCompact", "manual"))
        self.assertEqual(read("plan-mode", ended), ("at_prompt", "hook"))
        # Claude's own compaction runs inside a turn, whose Stop ends it
        turn = self.hook("UserPromptSubmit", prompt="Go on.")
        self.assertEqual(self.hook("PreCompact", trigger="auto", custom_instructions=None), turn)
        self.assertEqual(self.hook("PostCompact", trigger="auto", compact_summary="..."), turn)

    def test_an_event_heard_before_the_fact_standing_was_written_writes_nothing(self):
        # an answer's hook, which Claude does not wait on, finishing after the Stop that followed;
        # the hook reads the real clock, and this sandbox's time.time() is a fixed fake
        later = {"session": SEAT, "event": "Stop", "kind": "", "text": "",
                 "at": datetime.now().timestamp() + 60}
        config.hook_facts_path(SEAT).write_text(json.dumps(later))
        self.assertEqual(self.hook("PostToolUse", **ANSWERED), later)

    def test_the_hooks_verb_installs_each_new_event_unwaited(self):
        for run in range(2):
            done = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), "hooks"], text=True,
                                  capture_output=True, env=self.env, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("already runs hooks/seat-state.sh", done.stdout)
        hooks = json.loads((self.root / ".claude/settings.json").read_text())["hooks"]
        for event, matcher in (("PermissionRequest", None),
                               ("PostToolUse", "AskUserQuestion|ExitPlanMode"),
                               ("PreCompact", None), ("PostCompact", None)):
            with self.subTest(event=event):
                [group] = hooks[event]
                self.assertEqual(group.get("matcher"), matcher)
                self.assertEqual(group["hooks"], [{"type": "command", "async": True,
                    "command": f"bash {REPO}/hooks/seat-state.sh"}])
        # the turn's own events stay waited on: the Stop decides whether the turn may end
        self.assertNotIn("async", json.dumps(hooks["Stop"]))


class Read(unittest.TestCase):
    """The screen alone, where 2.1.263's rules read it wrong."""

    def test_each_screen_reads_what_the_seat_is_doing(self):
        # a 60-column pane cuts `esc to interrupt`, a wrapped spinner under a wrapped tip sits
        # nine rows up, a composer holding text drops the footer's hint, and a turn whose Stop
        # hooks still run is over: its Stop decides
        for what, state in (("narrow-working", "working"), ("narrow-streaming", "working"),
                            ("draft-while-working", "working"), ("compacting", "working"),
                            ("stop-hooks-running", None), ("manual-mode", "at_prompt"),
                            ("plan-mode", "at_prompt"), ("accept-edits", "at_prompt")):
            with self.subTest(what=what):
                self.assertEqual(watch.screen_state("claude", pane(what))[0], state)
        stopped = {"event": "Stop", "kind": "", "at": 100.0}
        self.assertEqual(read("stop-hooks-running", stopped), ("at_prompt", "hook"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A seat's word follows what its hooks last heard, read beside what its screen shows.

A harness's hooks say a turn began (a prompt, or a compaction the owner asked for), a permission
went up, or the turn ended, and ak reads that beside the seat's screen to give it one word.  A
turn in flight is `working` even while the composer is drawn; a permission dialog on screen is
`needs you`, decided by the hook; a turn that ended at the prompt is `idle`.  A permission the
hook still holds while the screen is back at the composer was answered, and the turn that asked
runs on, so the seat reads `working` and never asks the owner again (AGENTS.md: seats read
`needs you` for answered questions).  `ak orch why` and `ak orch list --why` say whether the
hook or a screen rule decided.  After one `ak watch` pass each seat's record and its terminal
title carry the word, and no seat at work pages the owner.

Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), in seats of tests/fixtures/akseat.py showing captures of real
Claude Code screens, paging tests/fixtures/sink.py; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks, transcript
from fixtures.sink import Sink

WIDE = {"COLUMNS": "200"}
PROMPT = ("UserPromptSubmit", {"prompt": "go"})
STOP = ("Stop", {"stop_hook_active": False})
PERMISSION = ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
NOTICE = ("Notification", {"notification_type": "permission_prompt",
                           "message": "Claude needs your permission to use Bash"})
COMPACT = ("PreCompact", {"trigger": "manual", "custom_instructions": ""})
QUESTION = ("PreToolUse", {"tool_name": "AskUserQuestion", "tool_input": {"questions": [
    {"question": "Which branch?", "header": "Branch", "multiSelect": False,
     "options": [{"label": "main", "description": ""}, {"label": "fix-api", "description": ""}]}
]}})
# Each seat: its screen, the events its hooks heard (oldest first), and the word it reads.
SEATS = {
    "acme": ("claude-prompt-pane.txt", (PROMPT, STOP), "idle"),
    "beta": ("claude-permission-pane.txt", (PROMPT, PERMISSION), "needs you"),
    "gamma": ("claude-prompt-pane.txt", (PROMPT, PERMISSION), "working"),
    "delta": ("claude-prompt-pane.txt", (PROMPT, NOTICE), "working"),
    "fix-api": ("claude-prompt-pane.txt", (PROMPT,), "working"),
    "parser": ("claude-prompt-pane.txt", (COMPACT,), "working"),
    "widgets": ("claude-working-pane.txt", (PROMPT,), "working"),
    "docs": ("claude-question-pane.txt", (PROMPT, QUESTION), "needs you"),
}
GLYPH = {"working": "● working", "needs you": "! needs you", "idle": "○ idle"}
COMPOSER = "  authority: screen  rule: prompt.composer"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HookWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(home, ["opus"])
        hooks = Hooks(home)
        for name, (screen, events, _) in SEATS.items():
            seat = Seat(home, name, screen=screen)
            said = transcript(home, name, "Done.")
            for event, payload in events:
                fired = hooks.fire(event, {**payload, "session_id": f"conv-{name}",
                                           "transcript_path": said, "cwd": str(seat.cwd)},
                                   seat=name, pane=seat)
                assert fired.code == 0, f"{name} {event}: {fired.err}"
        watched = home.ak("watch")
        assert watched.code == 0, watched.err
        state = home.path / ".agentkit" / "state"
        cls.records = {name: json.loads((state / f"seat-{name}.json").read_text())
                       for name in SEATS}
        cls.titles = {name: home.tmux("show-options", "-v", "-t", f"={name}:",
                                      "set-titles-string").out.strip() for name in SEATS}

    def why(self, name):
        done = self.home.ak("orch", "why", name, env=WIDE)
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()

    def blocks(self):
        """`ak orch list --why`: each seat's row, then the lines under it."""
        done = self.home.ak("orch", "list", "--why", env=WIDE)
        self.assertEqual(done.code, 0, done.err)
        blocks, name = {}, None
        for line in done.out.splitlines()[1:]:
            if line and not line.startswith(" "):
                name = line.split()[0]
                blocks[name] = [line]
            elif name:
                blocks[name].append(line)
        return blocks

    def test_a_turn_that_ended_at_the_prompt_is_idle_by_the_hook(self):
        lines = self.why("acme")
        self.assertEqual(lines[0], "acme  idle")
        self.assertIn("  authority: hook  rule: Stop", lines)

    def test_a_permission_dialog_the_hook_heard_needs_you_by_the_hook(self):
        self.assertEqual(self.why("beta")[:3],
                         ["beta  needs you", "  reason:    PermissionRequest",
                          "  authority: hook  rule: PermissionRequest/Bash"])

    def test_a_permission_still_held_once_the_composer_is_back_was_answered_and_works_on(self):
        for name in ("gamma", "delta"):
            with self.subTest(heard=SEATS[name][1][-1][0]):
                lines = self.why(name)
                self.assertEqual(lines[0], f"{name}  working")
                self.assertIn(COMPOSER, lines)

    def test_a_prompt_or_a_compaction_asked_for_works_on_while_the_composer_is_drawn(self):
        for name in ("fix-api", "parser"):
            with self.subTest(heard=SEATS[name][1][-1][0]):
                self.assertEqual(self.why(name)[0], f"{name}  working")

    def test_a_turn_running_on_screen_after_its_prompt_works_by_the_hook(self):
        lines = self.why("widgets")
        self.assertEqual(lines[0], "widgets  working")
        self.assertIn("  authority: hook  rule: UserPromptSubmit", lines)

    def test_each_row_of_the_list_shows_its_seats_word(self):
        done = self.home.ak("orch", "list", env=WIDE)
        self.assertEqual(done.code, 0, done.err)
        rows = {line.split()[0]: line for line in done.out.splitlines()[1:] if line.strip()}
        for name, (_, _, word) in SEATS.items():
            with self.subTest(seat=name):
                self.assertIn(GLYPH[word], rows[name])

    def test_the_list_says_the_hook_decided_the_permission_and_the_screen_the_question(self):
        blocks = self.blocks()
        for name, rule in (("beta", "  authority: hook  rule: PermissionRequest/Bash"),
                           ("docs", "  authority: screen  rule: asking.question")):
            with self.subTest(seat=name):
                self.assertIn(GLYPH["needs you"], blocks[name][0])
                self.assertIn(rule, blocks[name])

    def test_after_one_watch_each_seats_record_and_title_carry_its_word(self):
        for name, (_, _, word) in SEATS.items():
            with self.subTest(seat=name):
                self.assertEqual(self.records[name]["word"], word)
                self.assertEqual(self.titles[name], f"{name} · {word}")
        self.assertEqual(self.records["widgets"]["state"], "working")

    def test_no_seat_at_work_pages_the_owner(self):
        working = [name for name, (_, _, word) in SEATS.items() if word == "working"]
        for page in self.sink.pages():
            for name in working:
                self.assertNotIn(f"· {name}", str(page))


if __name__ == "__main__":
    unittest.main()

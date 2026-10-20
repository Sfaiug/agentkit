"""A relaunched seat opens on the line it goes on with, and nothing is typed into its TUI.

The tick typed a relaunch's line -- go on with the turn, the subscription moved, the handover --
ten seconds after the launch, into a TUI often still loading a long conversation: the Enter was
lost, or the owner's own typing merged with it.  Where the harness takes a first prompt on its
command line (`[launch] first_prompt`) the line now goes in as that.  `test_seat_move_keeps_
conversation`'s stage, with a stand-in adapter directory.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures.sandbox import REPO
from test_seat_move_keeps_conversation import NOW, OWN, SEAT, SeatMove
from agentkit import config, orch, watch

REAL_COMMAND = orch.command          # the stage stands one in; the adapter's own case runs this


class FirstPrompt(SeatMove):
    def setUp(self):
        super().setUp()
        # Claude Code takes a first prompt here; Codex, as far as this test knows, does not
        adapters = Path(tempfile.mkdtemp(dir=self.root))
        (adapters / "claude.toml").write_text(
            (REPO / "adapters/claude.toml").read_text() + "\n[launch]\nfirst_prompt = true\n")
        shutil.copy(REPO / "adapters/codex.toml", adapters / "codex.toml")
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.adapters, self.lines, self.typed = adapters, [], []
        command = orch.command.side_effect
        orch.command.side_effect = lambda *a, line=None, **kw: (self.lines.append(line)
                                                                 or command(*a, **kw))
        self.stack.enter_context(patch.object(
            watch, "type_into", side_effect=lambda _s, line, _log, stale, **_kw:
            None if stale(SEAT) else self.typed.append(line) or True))
        self.stack.enter_context(patch.object(watch, "INBOX_WARMUP", 0))   # a TUI listening at once

    def mid_turn(self):
        watch.seat_write(SEAT, state="at_prompt")
        config.record_hook_fact(SEAT, {"session": SEAT, "event": "UserPromptSubmit",
                                       "at": NOW - 30, "kind": "", "text": ""})

    def prompted(self):
        """The harness's own prompt hook stamps the first prompt it opened on."""
        config.stop_path(SEAT).write_text(json.dumps({"turn": NOW + 5}))

    def tick(self):
        watch.continue_turns(self.cfg, lambda _line: None)

    def test_the_adapter_is_handed_the_line_and_no_other(self):
        (self.adapters / "claude.sh").write_text(
            '#!/bin/sh\nprintf "acme-tui %s\\n" "$(printf %s "$AGENTKIT_FIRST_PROMPT" | '
            'python3 -c "import shlex,sys; print(shlex.quote(sys.stdin.read()))")"\n')
        (self.adapters / "claude.sh").chmod(0o755)
        with patch.dict(os.environ, {config.FIRST_PROMPT_ENV: "a stranger's line"}):
            said = 'Go on; "quote" $HOME\nand a second row'
            self.assertEqual(REAL_COMMAND(self.cfg, "opus", OWN, line=said)[-1], said)
            self.assertEqual(REAL_COMMAND(self.cfg, "opus", OWN)[-1], "")

    def test_a_seat_moved_mid_turn_opens_on_its_line_and_nothing_is_typed(self):
        self.mid_turn()
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.lines, [watch.MIDTURN_LINE])
        self.assertTrue(watch.seat_read(SEAT)["midturn"]["launched"])
        self.tick()                                  # its TUI is still loading the conversation
        self.assertEqual(self.typed, [])
        self.assertIsNotNone(watch.seat_read(SEAT).get("midturn"))
        self.prompted()
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_a_seat_at_rest_moved_on_its_harness_opens_on_no_line(self):
        self.assertEqual(self.move("fable"), "")
        self.assertEqual(self.lines, [None])
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_a_harness_that_takes_no_first_prompt_has_its_line_typed_as_before(self):
        self.mid_turn()
        self.assertEqual(self.move("astra"), "")
        mark = watch.seat_read(SEAT)["midturn"]
        self.assertNotIn("launched", mark)
        self.tick()
        self.assertEqual(self.typed, [watch.MOVED_LINE])

    def test_a_first_prompt_that_never_came_is_typed_once_its_passes_are_spent(self):
        self.mid_turn()
        self.move("fable")
        for _ in range(watch.MIDTURN_TRIES):
            self.tick()
        self.assertEqual(self.typed, [])
        self.tick()
        self.assertEqual(self.typed, [watch.MIDTURN_LINE])
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_a_seat_moved_to_another_subscription_opens_on_the_account_line(self):
        with patch.object(orch, "resume", return_value="resumed") as resume:
            watch._resume_on(self.cfg, SEAT, lambda _line: None, "second", True)
        self.assertEqual(resume.call_args.kwargs["line"], watch.ACCOUNT_LINE)
        self.assertTrue(watch.seat_read(SEAT)["midturn"]["launched"])


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stage's run from their own file."""
    return unittest.TestSuite(FirstPrompt(name) for name in loader.getTestCaseNames(FirstPrompt)
                              if name in vars(FirstPrompt))


if __name__ == "__main__":
    unittest.main()

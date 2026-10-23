"""A Claude Code seat's word is read off its screen, as the harness draws it.

Each screen is a capture of a real Claude Code pane in tests/fixtures; the seat shows it with no
hook fact beside it, so the screen is all the evidence `ak orch why` has.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat

WORDS = {
    "needs you": ("claude-dialog-pane.txt", "claude-permission-pane.txt", "claude-plan-pane.txt",
                  "claude-question-pane.txt", "claude-question-notes-pane.txt",
                  "claude-question-preview-pane.txt", "claude-question-ruled-footer-pane.txt",
                  "claude-question-scrolled-back-pane.txt"),
    "working": ("claude-working-pane.txt", "claude-compacting-pane.txt",
                "claude-narrow-working-pane.txt", "claude-tray-working-pane.txt",
                "claude-working-after-question-pane.txt",
                "claude-after-interrupt-next-turn-pane.txt", "claude-draft-while-working-pane.txt",
                "claude-narrow-streaming-pane.txt"),
    "idle": ("claude-prompt-pane.txt", "claude-accept-edits-pane.txt", "claude-auth-pane.txt",
             "claude-auth-401-pane.txt", "claude-interrupted-pane.txt",
             "claude-plan-mode-pane.txt", "claude-prompt-scrolled-pane.txt",
             "claude-scrolled-line-pane.txt", "claude-scrolled-line-and-owner-words-pane.txt",
             "claude-suggestion-pane.txt", "claude-tray-idle-pane.txt", "unknown-logout-pane.txt",
             "unknown-stuck-pane.txt", "claude-folded-line-pane.txt",
             "claude-folded-line-and-owner-words-pane.txt", "claude-question-scrolled-pane.txt",
             "claude-stop-hooks-running-pane.txt"),
}


class ClaudeWords(unittest.TestCase):
    def test_each_screen_reads_as_its_word(self):
        for word, screens in WORDS.items():
            for screen in screens:
                with self.subTest(screen=screen), Home() as home:
                    Seat(home, "acme", model="opus", screen=screen)
                    done = home.ak("orch", "why", "acme")
                    self.assertEqual(done.code, 0, done.err)
                    self.assertEqual(done.out.splitlines()[0].split(), ["acme", *word.split()])


if __name__ == "__main__":
    unittest.main()

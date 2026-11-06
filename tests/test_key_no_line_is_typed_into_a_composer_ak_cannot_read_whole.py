"""No line is typed into a composer ak cannot read whole; one read empty takes it.

Claude Code scrolls a long draft inside its box, and `watch.composer_draft` cannot read that
screen whole -- nor with its top above the capture, nor without its key-hint row.  A line typed
there would join the owner's unsent text, and its Enter would send both.  `tell_parked` types a
parked run's line into its seat whatever state the seat reads, so it goes out as its card
instead.  Offline: `orch.tmux_out` records each send and serves the screen.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, handback, notify, orch, watch

FIX = REPO / "tests/fixtures"
SCROLLED = (FIX / "claude-scrolled-draft-pane.txt").read_text(encoding="utf-8").splitlines()
UNREAD = {
    "whole": "\n".join(SCROLLED),
    "its bottom twelve rows": "\n".join(SCROLLED[-12:]),
    "without its last row": "\n".join(SCROLLED[:-1]),
}
EMPTY = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")


class NoLineIntoAComposerReadInPart(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-composer-read-whole-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
        }))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        config.ensure_dirs()
        self.sent, self.pane = [], ""
        stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        stack.enter_context(patch.object(orch, "find", return_value={"name": "acme"}))
        stack.enter_context(patch.object(handback, "launcher_watched", return_value=True))
        stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "anthropic")))
        stack.enter_context(patch.object(watch.time, "sleep"))
        self.card = stack.enter_context(patch.object(notify, "shaped", return_value=0))

    def tmux(self, *args, **_kw):
        if args[0] == "send-keys":
            self.sent.append(args[-1])
        return 0, self.pane if args[0] == "capture-pane" else ""

    def park(self):
        return watch.tell_parked("20261105-fix-api", "review", "acme", lambda _: None)

    def test_a_composer_read_in_part_gets_no_keys_and_an_empty_one_takes_the_line(self):
        for kind, pane in UNREAD.items():
            with self.subTest(kind=kind):
                self.card.reset_mock()
                self.pane = pane
                self.assertTrue(self.park())
                self.assertEqual(self.sent, [])
                self.card.assert_called_once()
        self.card.reset_mock()
        self.pane = EMPTY
        self.assertTrue(self.park())
        self.assertIn("ak run resume 20261105-fix-api", self.sent[0])
        self.assertEqual(self.sent[1:], ["Enter"])
        self.card.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

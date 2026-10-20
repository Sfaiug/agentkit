"""No key of ak's goes into a dialog OpenCode draws over its transcript -- its models, commands,
sessions, themes.  Such a dialog sits wherever centring leaves it, above the rows a seat's state
is read off; what is typed goes into its search and Enter picks a row.  OpenCode keeps the
terminal cursor in its composer's box while keys go there and moves it into the dialog, so ak
sends keys only while the cursor sits in that box, whatever text the screen shows (20 Oct 2026).
Offline: real 2.0.32 captures, renamed, with the cursor row each was taken at, and tmux faked.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, watch  # noqa: E402

FIX = REPO / "tests/fixtures"
SEAT = {"name": "acme", "created": 10, "legacy": False}
WHERE = {"id": "%7", "tty": "/dev/null", "keys": ("C-x", "e")}


class KeysGoWhereTheCursorIs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-cursor-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        patches = [patch.dict(os.environ, {"HOME": str(root), "AGENTKIT_SESSION": ""}),
                   patch.object(orch, "tmux_out", side_effect=self.tmux),
                   patch.object(watch, "pane_unread", return_value=False),
                   patch.object(watch, "SENT_WAIT", 0)]
        patches += [patch.object(config, name, root / ".agentkit" / name.lower())
                    for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV",
                                 "CODE")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        config.ensure_dirs()
        config.save_session(config.load(), SEAT["name"], "mimo", ["mimo"], {"cwd": str(root)})
        self.cursor, self.keys = (0, ""), []

    def tmux(self, *args, **_kw):
        if args[0] == "display-message" and args[-1] == "#{cursor_y}":
            return self.cursor
        if args[0] == "capture-pane":
            return 0, self.pane
        if args[0] == "send-keys":
            self.keys.append(args[3:])
        return 0, ""

    def shown(self, name, row):
        self.pane = (FIX / f"opencode-cursor-{name}-pane.txt").read_text(encoding="utf-8")
        self.cursor = (0, f"{row}\n")

    def test_a_dialog_over_the_transcript_takes_no_key(self):
        self.shown("model-dialog", 11)      # its search row
        self.assertIsNone(watch._send_line(SEAT, "Build finished.", lambda _: None))
        self.assertFalse(watch._send_enter(SEAT, lambda _: None))
        self.assertIsNone(watch._edit(SEAT, WHERE, "line", "Build finished."))
        self.assertEqual(self.keys, [])

    def test_keys_go_while_the_cursor_is_in_the_composer_whatever_the_text_shows(self):
        for name in ("prompt", "quoted-dialog"):    # a dialog's title quoted in the transcript
            with self.subTest(name=name):
                self.shown(name, 24)
                self.keys = []
                self.assertFalse(watch.off_composer(SEAT))
                self.assertTrue(watch._send_enter(SEAT, lambda _: None))
                self.assertEqual(self.keys, [("Enter",)])

    def test_a_cursor_that_cannot_be_read_takes_no_key(self):
        self.shown("prompt", 24)
        self.cursor = (1, "no such pane")
        self.assertFalse(watch._send_enter(SEAT, lambda _: None))
        self.assertEqual(self.keys, [])

    def test_a_harness_keeping_no_cursor_there_is_never_asked(self):
        config.save_session(config.load(), SEAT["name"], "opus", ["opus"], {"cwd": "/"})
        self.shown("model-dialog", 11)
        self.assertFalse(watch.off_composer(SEAT))


if __name__ == "__main__":
    unittest.main()

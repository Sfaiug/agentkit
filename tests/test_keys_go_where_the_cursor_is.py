"""No key of ak's goes into a dialog OpenCode draws over its transcript -- its models, commands,
sessions, themes.  Such a dialog sits wherever centring leaves it, above the rows a seat's state
is read off; what is typed goes into its search and Enter picks a row.  OpenCode keeps the
terminal cursor in its composer's box while keys go there and moves it into the dialog, so ak
sends keys only while the cursor sits in that box, whatever text the screen shows (20 Oct 2026).
Offline: real 2.0.32 captures, renamed, with the cursor row each was taken at, and tmux faked
under `orch.tmux_out`, which strips what tmux prints.
"""

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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
                   patch.object(orch.subprocess, "run", side_effect=self.tmux),
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
        self.keys = []

    def tmux(self, argv, **_kw):
        """What tmux 3.5a prints: the cursor's row, and every row of the pane, blank ones too."""
        args, out = argv[3:] if argv[1] == "-L" else argv[1:], ""
        if args[0] in ("display-message", "capture-pane") and self.row is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="can't find pane: acme\n")
        if args == ["display-message", "-p", "-t", "=acme:", "#{cursor_y}"]:
            out = f"{self.row}\n"
        elif args == ["capture-pane", "-p", "-t", "=acme:"]:
            out = self.pane
        elif args[0] == "send-keys":
            self.keys.append(tuple(args[3:]))
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    def shown(self, name, row):
        self.pane = (FIX / f"{name}-pane.txt").read_text(encoding="utf-8")
        self.row = row

    def test_a_dialog_over_the_transcript_takes_no_key(self):
        self.shown("opencode-cursor-model-dialog", 11)      # its search row
        self.assertIsNone(watch._send_line(SEAT, "Build finished.", lambda _: None))
        self.assertFalse(watch._send_enter(SEAT, lambda _: None))
        self.assertIsNone(watch._edit(SEAT, WHERE, "line", "Build finished."))
        self.assertEqual(self.keys, [])

    def test_keys_go_while_the_cursor_is_in_the_composer_whatever_the_text_shows(self):
        # a dialog's title quoted in the transcript; a fresh prompt drawn under blank rows
        for name, row in (("opencode-cursor-prompt", 24), ("opencode-cursor-quoted-dialog", 24),
                          ("opencode-prompt", 16)):
            with self.subTest(name=name):
                self.shown(name, row)
                self.keys = []
                self.assertFalse(watch.off_composer(SEAT))
                self.assertTrue(watch._send_enter(SEAT, lambda _: None))
                self.assertEqual(self.keys, [("Enter",)])

    def test_a_cursor_that_cannot_be_read_takes_no_key(self):
        self.shown("opencode-cursor-prompt", None)
        self.assertFalse(watch._send_enter(SEAT, lambda _: None))
        self.assertEqual(self.keys, [])

    def test_a_harness_keeping_no_cursor_there_is_never_asked(self):
        config.save_session(config.load(), SEAT["name"], "opus", ["opus"], {"cwd": "/"})
        self.shown("opencode-cursor-model-dialog", 11)
        self.assertFalse(watch.off_composer(SEAT))


if __name__ == "__main__":
    unittest.main()

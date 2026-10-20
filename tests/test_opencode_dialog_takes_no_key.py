"""A dialog OpenCode draws over its transcript -- its models, commands, sessions, themes -- sits
wherever centring leaves it, above the rows a seat's state is read off.  A key typed there goes
into its search and Enter picks a row, so while one shows the seat reads as the owner's own
hand, a draft, and takes no line (20 Oct 2026).  Offline: a real 2.0.32 seat's capture, renamed,
read in a temporary HOME with no hook fact.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, watch  # noqa: E402

FIX = REPO / "tests/fixtures"
SEAT = {"name": "acme", "created": 10, "legacy": False}


class DialogOverTheTranscript(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-dialog-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        patches = [patch.dict(os.environ, {"HOME": str(root), "AGENTKIT_SESSION": ""})]
        patches += [patch.object(config, name, root / ".agentkit" / name.lower())
                    for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV",
                                 "CODE")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, SEAT["name"], "mimo", ["mimo"], {"cwd": str(root)})

    def read(self, name):
        """(state, rule, takes a line) of that capture."""
        pane = (FIX / f"opencode-{name}-pane.txt").read_text(encoding="utf-8")
        found = watch.live_state(SEAT, "opencode", pane=pane, cfg=self.cfg)
        return found["state"], found["rule"], watch.takes_line(SEAT, cfg=self.cfg, pane=pane)

    def test_a_dialog_over_the_transcript_takes_no_line(self):
        self.assertEqual(self.read("model-dialog"), ("draft", "modal", False))
        # over a composer holding the owner's text too
        self.assertEqual(self.read("command-dialog"), ("draft", "modal", False))

    def test_a_screen_with_none_reads_as_it_did(self):
        self.assertEqual(self.read("prompt"), ("at_prompt", "prompt.composer", True))
        self.assertEqual(self.read("working")[:2], ("working", "working.interrupt"))
        self.assertEqual(self.read("dialog")[:2], ("asking", "asking.permission"))

    def test_text_like_its_title_in_the_transcript_is_none(self):
        # a reply drawn on the screen's own background, however it is spaced, or one row of it
        # on a block's background of its own
        pane = (FIX / "opencode-prompt-pane.txt").read_text(encoding="utf-8")
        title = "    Select model                     esc    "
        for said in ("Close dialog          esc", title,
                     f"\x1b[48;2;4;4;4m  \x1b[48;2;12;12;12m{title}\x1b[48;2;4;4;4m"):
            with self.subTest(said=said):
                self.assertIsNone(watch.modal_row("opencode", f"{said}\n{pane}"))

    def test_one_the_owner_searches_in_is_one(self):
        pane = (FIX / "opencode-model-dialog-pane.txt").read_text(encoding="utf-8")
        self.assertEqual(watch.modal_row("opencode", pane.replace("mSearch", "mdeep  ")),
                         "Select model                                     esc")

    def keys(self, name, send):
        """The keys `send` puts into a seat showing that capture, and what it returned."""
        pane = (FIX / f"opencode-{name}-pane.txt").read_text(encoding="utf-8")
        sent = []

        def tmux(*args, **_kw):
            if args[0] != "capture-pane":
                sent.append(args)
            return 0, pane if args[0] == "capture-pane" else ""
        with patch.object(watch.orch, "tmux_out", tmux), \
                patch.object(watch, "pane_unread", return_value=False):
            done = send()
        return [args for args in sent if args[0] == "send-keys"], done

    def test_no_key_goes_into_one(self):
        # every sender's line and Enter, the merge question's, a parked run's notice and the
        # Enter a receipt owes alike, go through these two
        line = "and add these posts"
        mark = {"line": line, "seat": SEAT["created"]}
        for send in (lambda: watch._send_line(SEAT, line, print),
                     lambda: watch._send_enter(SEAT, print),
                     lambda: watch.type_at_prompt(SEAT, line, print, cfg=self.cfg, typed=mark)):
            self.assertEqual(self.keys("command-dialog", send)[0], [])
        self.assertTrue(self.keys("prompt", lambda: watch._send_enter(SEAT, print))[0])


if __name__ == "__main__":
    unittest.main()

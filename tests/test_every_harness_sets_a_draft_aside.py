"""Every harness takes ak's line through ak's editor past the owner's unsent text, and gives that
text back, OpenCode and Grok included.

A seat sat with ak's line untyped while the owner's text held its composer, and the owner asked
for the fix in every harness and model (19 Oct 2026).  Each manifest names the keys that hand its
composer to $VISUAL, ak's editor in every seat: OpenCode 2.0.32 drops Ctrl-X typed alone while it
opens a new session, so its keys go in one write; Grok 1.0.46 opens it only from its command
palette, each key typed once the palette shows the one before it landed.  Offline: tmux and each
harness's editor keys faked in memory, around the real agentkit/aside_editor.py.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from agentkit import aside_editor, orch, watch  # noqa: E402

PANE = "%7"
DRAFT = "and add these posts"
LINE = "run 20261019-2223 finished PASS merged"
SEAT = {"name": "acme", "created": 10, "legacy": False}
# what Grok's command palette draws as each key lands (1.0.46)
PALETTE = {"C-p": "│   search: ", "edit prompt": "│   search: edit prompt   │"}


class EveryHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-every-aside-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "composer.md"
        self.ask, self.buffers, self.keys, self.shown = None, {}, [], ""
        self.where, self.composer, self.opens, self.opening = None, DRAFT, True, False
        for target, name, fake in ((aside_editor, "_tmux", self.editor_tmux),
                                   (orch, "tmux_out", self.tmux),
                                   (watch.time, "sleep", lambda _seconds: None)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seat(self, harness):
        chrome = watch.screen(harness)
        self.where = {"id": PANE, "tty": "", "keys": chrome["editor"],
                      "shows": chrome["editor_shows"]}

    def tmux(self, *args, socket=None):
        """The seat's server: the ask set on its pane, and its harness taking its keys."""
        if args[0] == "set-option":
            self.ask = None if "-pu" in args else args[-1]
        elif args[0] == "capture-pane":
            return 0, self.shown
        elif args[0] == "send-keys":
            sent, keys = args[args.index("-t") + 2:], self.where["keys"]
            # a harness opening a new session drops the first key of a chord when it comes alone
            if self.opening and sent == keys[:1]:
                return 0, ""
            for key in sent:
                self.keys.append(key)
                self.shown = PALETTE.get(key, "") if self.opens else ""
                if tuple(self.keys[-len(keys):]) == keys:
                    self.edit()
                elif len(key) == 1:         # a letter outside its chord is typed
                    self.composer += key
        return 0, ""

    def edit(self):
        """The harness's editor keys: its composer handed to $VISUAL, and what that leaves taken."""
        self.path.write_text(self.composer)
        with patch.dict(os.environ, {"TMUX_PANE": PANE}):
            aside_editor.edit([str(self.path)])
        self.composer = self.path.read_text()

    def editor_tmux(self, *args, data=None):
        """tmux as ak's editor asks it, in the pane it runs in."""
        if args[0] == "show-options":
            said, self.ask = self.ask, None
            return f"{said}\n".encode() if said else b""
        if args[0] == "list-buffers":
            return "".join(f"{name}\n" for name in self.buffers).encode()
        name = args[args.index("-b") + 1]
        if args[0] == "save-buffer":
            return self.buffers.get(name)
        if args[0] == "load-buffer":
            self.buffers[name] = data
        else:
            self.buffers.pop(name, None)
        return b""

    def line_and_back(self):
        self.assertTrue(watch._edit(SEAT, self.where, "line", LINE,
                                    settled=lambda: self.composer == LINE))
        self.assertEqual((self.composer, self.buffers),
                         (LINE, {aside_editor.kept(PANE): DRAFT.encode()}))
        self.composer = ""              # sent
        self.assertTrue(watch._edit(SEAT, self.where, "back",
                                    settled=lambda: self.composer == DRAFT))
        self.assertEqual((self.composer, self.buffers, self.ask), (DRAFT, {}, None))

    def test_every_harness_takes_a_line_past_the_owners_text_and_gives_it_back(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            with self.subTest(manifest.stem):
                self.seat(manifest.stem)
                self.composer, self.keys = DRAFT, []
                self.line_and_back()

    def test_a_harness_opening_a_new_session_takes_its_editor_keys_whole(self):
        self.seat("opencode")
        self.opening = True
        self.line_and_back()

    def test_a_palette_that_never_opens_gets_none_of_the_keys_meant_for_it(self):
        self.seat("grokbuild")
        self.opens = False
        self.assertFalse(watch._edit(SEAT, self.where, "line", LINE,
                                     settled=lambda: self.composer == LINE))
        # the rest would have gone into the owner's composer; no ask is left for their own edit
        self.assertEqual((self.keys, self.composer, self.ask, self.buffers),
                         (["C-p"], DRAFT, None, {}))


if __name__ == "__main__":
    unittest.main()

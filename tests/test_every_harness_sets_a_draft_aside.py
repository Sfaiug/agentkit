"""Every harness hands its composer to ak's editor on the keys its manifest names, so the owner's
unsent text is set aside for ak's line and given back, Muse, OpenCode and Grok included.

A seat sat with ak's line untyped while the owner's text held its composer, and the owner asked
for the fix in every harness and model (19 Oct 2026).  OpenCode 2.0.32 drops a ctrl+x typed
alone while it opens a new session, so its keys go in one write; Grok 1.0.46 opens the editor
only from its command palette, each key typed once the palette shows the one before it landed.
Offline: tmux and each harness's editor keys faked in memory, around the real
agentkit/aside_editor.py.
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
LINE = "run acme-parser ended PASS"
SEAT = {"name": "acme", "created": 10, "legacy": False}
KEPT = aside_editor.kept(PANE)
# what Grok's command palette draws as each key lands (1.0.46)
PALETTE = {"C-p": "│   search: ", "edit prompt": "│   search: edit prompt   │"}


class EveryHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-every-aside-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "composer.md"
        self.ask, self.buffers, self.keys, self.shown = None, {}, [], ""
        self.where, self.composer, self.opens, self.opening = None, DRAFT, True, False
        self.now, self.slow, self.drawn = 1e6, 0, 0
        for target, name, fake in ((aside_editor, "_tmux", self.editor_tmux),
                                   (orch, "tmux_out", self.tmux),
                                   (watch.time, "time", lambda: self.now),
                                   (watch.time, "sleep", self.sleep),
                                   # an ask it finds stale opens the owner's own editor
                                   (aside_editor.os, "execvp", lambda *args: self.fail(args))):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seat(self, harness):
        chrome = watch.screen(harness)
        self.where = {"id": PANE, "tty": "", "keys": chrome["editor"],
                      "shows": chrome["editor_shows"]}

    def sleep(self, seconds):
        self.now += seconds

    def tmux(self, *args, socket=None):
        """The seat's server as ak asks it: the ask on its pane, its screen, and its harness
        taking its keys."""
        if args[0] == "set-option":
            self.ask = None if "-pu" in args else args[-1]
        elif args[0] == "show-options":
            return 0, f"{self.ask}\n" if self.ask else ""
        elif args[0] == "capture-pane":
            return 0, self.shown if self.now >= self.drawn else ""
        elif args[0] == "send-keys":
            sent, keys = args[args.index("-t") + 2:], self.where["keys"]
            self.drawn = self.now + self.slow   # what it draws for them, `slow` seconds on
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
        """The harness's editor keys: its composer handed to $VISUAL, `slow` seconds on, and what
        that leaves taken."""
        self.sleep(self.slow)
        self.path.write_text(self.composer)
        with patch.dict(os.environ, {"TMUX_PANE": PANE}):
            aside_editor.edit([str(self.path)])
        self.composer = self.path.read_text()

    def editor_tmux(self, *args, data=None):
        """tmux as ak's editor asks it, in the pane it runs in."""
        if args[0] == "show-options":       # the ask, read and cleared in one call
            said, self.ask = self.ask, None
            return f"{said}\n".encode() if said else b""
        if args[0] == "set-option":         # its answer
            self.ask = args[-1]
            return b""
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

    def aside_and_back(self):
        self.assertEqual(watch._edit(SEAT, self.where, "line", LINE), "line")
        self.assertEqual((self.composer, self.buffers),
                         (LINE, {KEPT: aside_editor.pack(aside_editor.ASIDE, LINE.encode(),
                                                         DRAFT.encode())}))
        self.composer = ""                  # its Enter sent the line
        self.assertEqual(watch._edit(SEAT, self.where, "back", LINE), "sent")
        self.assertEqual((self.composer, self.buffers, self.ask),
                         (DRAFT, {KEPT: aside_editor.pack(aside_editor.GIVEN, LINE.encode(),
                                                          DRAFT.encode())}, None))

    def test_every_harness_sets_the_owners_text_aside_and_gives_it_back(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            with self.subTest(manifest.stem):
                self.seat(manifest.stem)
                self.assertTrue(self.where["keys"])
                self.composer, self.keys, self.buffers = DRAFT, [], {}
                self.aside_and_back()

    def test_a_harness_opening_a_new_session_takes_its_editor_keys_whole(self):
        self.seat("opencode")
        self.opening = True
        self.aside_and_back()

    def test_a_palette_that_never_opens_gets_none_of_the_keys_meant_for_it(self):
        self.seat("grokbuild")
        self.opens = False
        self.assertIsNone(watch._edit(SEAT, self.where, "line", LINE))
        # the rest would have gone into the owner's composer; no ask is left for their own edit
        self.assertEqual((self.keys, self.composer, self.ask, self.buffers),
                         (["C-p"], DRAFT, None, {}))

    def test_a_palette_slow_to_open_still_hands_the_composer_to_ak_s_editor(self):
        # each menu and the editor take most of a wait: ak's editor takes only an ask as fresh
        self.seat("grokbuild")
        self.slow = watch.SENT_WAIT - 1
        self.assertGreater(self.slow * len(self.where["keys"]), aside_editor.FRESH)
        self.aside_and_back()


if __name__ == "__main__":
    unittest.main()

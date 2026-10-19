"""Text the owner left standing in a seat's composer never keeps ak's line out of it.

A seat ended its turn on `ak wait`; the run merged, and its end could not be typed in while the
owner's unsent text held the composer, so the seat sat (19 Oct 2026).  ak's editor -- the seat's
own $VISUAL -- takes that text out of the composer for ak's line, and hands it back once the
composer reads empty.  Offline: fixtures.seats' throwaway seats, its tmux faked as a composer
whose Ctrl-G opens the real agentkit/aside_editor.py.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.seats import SEAT, Seats
from agentkit import aside_editor, watch

DRAFT = "and add these posts"
PANE = "%7"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.keys, self.buffers, self.options, self.deaf = [], {}, {}, False
        self.active, self.listed, self.drawn = PANE, True, None
        for patcher in (patch.object(aside_editor, "_tmux", side_effect=self.editor_tmux),
                        patch.object(watch.time, "sleep", side_effect=self.draw)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show(DRAFT)

    def show(self, composer):
        self.composer = composer
        self.pane = self.base.replace(self.empty, f"❯ {composer}\n") if composer else self.base
        self.free = not composer

    def tmux(self, *args, **kwargs):
        command = args[0]
        # a seat's `=name:` is whichever of its panes the owner has active
        target = args[args.index("-t") + 1] if "-t" in args else ""
        target = self.active if target == f"={SEAT}:" else target
        if command == "display-message" and args[-1].startswith("#{pane_id}"):
            return 0, f"{self.active}\t4242\t{self.root / 'tty'}"
        if command == "set-option" and "-pu" in args:
            self.options.pop((target, args[-1]), None)
        elif command == "set-option":
            self.options[target, args[-2]] = args[-1]
        elif command == "list-buffers":
            return (0, "\n".join(self.buffers)) if self.listed else (1, "no server running")
        elif command == "list-panes":
            return 0, f"{PANE}\t{SEAT}"
        elif command == "delete-buffer":
            self.buffers.pop(args[-1], None)
        elif command == "send-keys" and "-l" not in args:
            self.keys.extend(args[args.index("-t") + 2:])
            if args[-1] == "C-g" and not self.deaf:
                self.edit()
        else:
            return super().tmux(*args, **kwargs)
        return 0, ""

    def edit(self):
        """The harness's Ctrl-G: its composer handed to $VISUAL, and what that leaves taken in
        at its next draw."""
        path = self.root / "composer.md"
        path.write_text(self.composer)
        with patch.dict(os.environ, {"TMUX_PANE": PANE}):
            aside_editor.edit([str(path)])
        self.drawn = path.read_text()

    def draw(self, _seconds):
        if self.drawn is not None:
            self.show(self.drawn)
            self.drawn = None

    def editor_tmux(self, *args, data=None):
        """tmux as ak's editor asks it, in the pane it runs in."""
        if args[0] == "show-options":
            return self.options.pop((args[3], aside_editor.ASK), "").encode()
        if args[0] == "save-buffer":
            return self.buffers.get(args[-2])
        if args[0] == "load-buffer":
            self.buffers[args[-2]] = data
            return b""
        return self.tmux(*args)[1].encode()

    def test_text_kept_past_its_pass_comes_back_once_the_composer_is_empty(self):
        self.buffers = {aside_editor.kept(PANE): DRAFT.encode(), aside_editor.kept("%3"): b"x"}
        self.show("newer words")
        watch.drafts_back(self.cfg, lambda _: None)
        # never beside the owner's newer text; what a pane gone kept goes with it
        self.assertEqual((self.keys, list(self.buffers)), ([], [aside_editor.kept(PANE)]))
        self.show("")
        watch.drafts_back(self.cfg, lambda _: None)
        # drawn before the lock lets another line at the composer
        self.assertEqual((self.keys, self.composer, self.buffers), (["C-g"], DRAFT, {}))

    def test_an_ask_its_harness_never_acts_on_is_taken_back_before_the_owners_edit(self):
        self.buffers, self.deaf = {aside_editor.kept(PANE): DRAFT.encode()}, True
        self.show("")

        def owner(_seconds):
            # mid-wait the owner moves to another pane, and tmux cannot list its buffers
            self.active, self.listed = "%8", False

        with patch.object(watch.time, "sleep", side_effect=owner):
            watch.drafts_back(self.cfg, lambda _: None)
        # the owner's own Ctrl-G later opens their editor: no ask is left for it to take
        self.assertEqual((self.keys, self.options), (["C-g"], {}))
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): DRAFT.encode()})


if __name__ == "__main__":
    unittest.main()

"""Text the owner left standing in a seat's composer never keeps ak's line out of it.

A seat ended its turn on `ak wait`; the run merged, and its end could not be typed in while the
owner's unsent text held the composer, so the seat sat (19 Oct 2026).  Once nothing has been
typed into the seat for a while, ak's editor -- the seat's own $VISUAL -- takes that text out of
the composer, ak's line goes in, and the text comes back.  Offline: fixtures.seats' throwaway
seats, its tmux faked as a composer whose Ctrl-G opens the real agentkit/aside_editor.py.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, SEAT, Seats
from agentkit import aside_editor, watch

DRAFT = "and add these posts"
PANE = "%7"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.composer, self.keys, self.sent, self.buffers, self.options = DRAFT, [], [], {}, {}
        self.panes, self.slow = [PANE], False
        self.tty = self.root / "tty"
        self.tty.write_text("")
        self.idle(watch.DRAFT_STILL)
        self.launched = True
        for name, fake in (("launched", lambda _pid, _tty: self.launched),
                           ("_tmux", self.editor_tmux)):
            patcher = patch.object(aside_editor, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show()

    def idle(self, seconds):
        """Nothing typed into the seat's pane for that long."""
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def show(self):
        self.pane = (self.base.replace(self.empty, f"❯ {self.composer}\n") if self.composer
                     else self.base)
        self.free = not self.composer

    def tmux(self, *args, **kwargs):
        command = args[0]
        if command == "display-message" and args[-1].startswith("#{pane_id}"):
            return 0, f"{PANE}\t4242\t{self.tty}"
        if command == "set-option":
            self.options[args[-2]] = args[-1]
            return 0, ""
        if command == "show-options":
            return 0, self.options.get(args[-1], "")
        if command == "list-buffers":
            return 0, "\n".join(self.buffers)
        if command == "list-panes":
            return 0, "\n".join(f"{pane}\t{SEAT}" for pane in self.panes)
        if command == "delete-buffer":
            self.buffers.pop(args[-1], None)
            return 0, ""
        if command != "send-keys":
            return super().tmux(*args, **kwargs)
        key = args[-1]
        self.keys.append("text" if "-l" in args else key)
        if "-l" in args:
            self.typed.append(key)
            self.composer += key
        elif key == "Enter" and self.composer and not self.slow:
            self.sent.append(self.composer)
            self.composer = ""
        elif key == "C-g":
            self.edit()
        self.show()
        return 0, ""

    def edit(self):
        """The harness's Ctrl-G: its composer handed to $VISUAL, and what that leaves taken."""
        path = self.root / "composer.md"
        path.write_text(self.composer)
        with patch.dict(os.environ, {"TMUX_PANE": PANE}):
            aside_editor.edit([str(path)])
        self.composer = path.read_text()

    def editor_tmux(self, *args, data=None):
        """tmux as ak's editor asks it, in the pane it runs in."""
        if args[0] == "show-options":
            return self.options.pop(aside_editor.ASK, "").encode()
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

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.tick()
        self.assertEqual(self.keys, ["C-g", "text", "Enter", "C-g"])
        self.assertEqual(self.sent, [LINE])
        self.assertEqual(self.composer, DRAFT)
        self.assertEqual(self.buffers, {})
        self.assertTrue(self.told())

    def test_text_in_a_composer_read_at_its_prompt_is_set_aside_too(self):
        # OpenCode 2.0.32 reads its prompt with the owner's text in the composer it draws
        with patch.object(watch, "at_prompt", return_value=True):
            self.wait_line()
            self.tick()
        self.assertEqual((self.sent, self.composer), ([LINE], DRAFT))
        self.assertTrue(self.told())

    def test_a_line_its_seat_takes_late_is_told_once_the_owners_text_is_back(self):
        self.wait_line()
        self.slow = True
        self.tick()
        self.assertEqual((self.composer, self.told()), (LINE, False))
        # the harness takes it a minute on, and the tick brings the owner's text back first
        self.slow, self.sent, self.composer = False, [LINE], ""
        self.show()
        watch.time.time = lambda: NOW + 60
        watch.drafts_back(self.cfg, lambda _: None)
        self.tick()
        self.assertEqual((self.composer, self.sent), (DRAFT, [LINE]))
        self.assertTrue(self.told())

    def test_text_typed_into_lately_or_in_a_seat_started_before_the_editor_is_left_alone(self):
        self.wait_line()
        self.idle(watch.DRAFT_STILL - 10)
        self.tick()
        self.idle(watch.DRAFT_STILL)
        self.launched = False
        self.tick()
        self.assertEqual(self.keys, [])
        self.assertEqual(self.composer, DRAFT)
        self.assertFalse(self.told())

    def test_text_kept_past_its_pass_comes_back_once_the_composer_is_empty(self):
        self.buffers = {aside_editor.kept(PANE): DRAFT.encode(), aside_editor.kept("%3"): b"x"}
        self.composer = "newer words"
        self.show()
        watch.drafts_back(self.cfg, lambda _: None)
        # never beside the owner's newer text; what a pane gone kept goes with it
        self.assertEqual((self.keys, list(self.buffers)), ([], [aside_editor.kept(PANE)]))
        self.composer = ""
        self.show()
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.composer, self.buffers), (DRAFT, {}))


if __name__ == "__main__":
    unittest.main()

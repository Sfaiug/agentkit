"""ak's lines go into a seat through ak's editor whatever its composer holds, and the owner's
text that held it comes back.

A seat's run merged and its end could not be typed while the owner's unsent text held the
composer, so the seat sat and paged them (19 Oct 2026).  A harness acts on its keys in order, so
a line never lands on text on its way back.  Offline: fixtures.seats' seats, their tmux faked as
a harness whose Ctrl-G hands its composer to the real agentkit/aside_editor.py.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, REPO, SEAT, Seats
from agentkit import aside_editor, watch
from agentkit.watch import seat_editor

DRAFT = "and add these posts"
PANE = "%7"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.keys, self.sent, self.buffers, self.ask, self.handed = [], [], {}, None, None
        self.deaf, self.slow, self.late_draw, self.launched = False, False, False, True
        self.tty = self.root / "tty"
        self.tty.write_text("")
        self.untouched(watch.DRAFT_STILL)
        for target, name, fake in ((aside_editor, "launched", lambda _pid, _tty: self.launched),
                                   (aside_editor, "_tmux", self.editor_tmux),
                                   (watch, "seat_editor", seat_editor)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show(DRAFT)

    def untouched(self, seconds):
        """Nothing typed into the seat's pane for that long."""
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def show(self, composer):
        self.composer, self.free = composer, not composer
        self.pane = self.base.replace(self.empty, f"❯ {composer}\n") if composer else self.base

    def tmux(self, *args, **kwargs):
        """The seat's server: its pane, the ask on it, its buffers, and its harness's keys."""
        command = args[0]
        if command == "display-message" and args[-1].startswith("#{pane_id}"):
            return 0, f"{PANE}\t4242\t{self.tty}"
        if command == "show-options":
            said = self.ask or ""
            if ";" in args:             # read and taken back at once
                self.ask = None
            return 0, said
        if command == "set-option":
            self.ask = None if "-pu" in args else args[-1]
        elif command == "list-buffers":
            return 0, "\n".join(self.buffers)
        elif command == "list-panes":
            return 0, f"{PANE}\t{SEAT}"
        elif command == "delete-buffer":
            self.buffers.pop(args[-1], None)
        elif command == "send-keys" and "-l" not in args:
            for key in args[args.index("-t") + 2:]:
                self.press(key)
        else:
            return super().tmux(*args, **kwargs)
        return 0, ""

    def press(self, key):
        """One key, after whatever the editor last handed back is drawn."""
        self.keys.append(key)
        if self.handed is not None:
            self.show(self.handed)
            self.handed = None
        if key == "C-g" and not self.deaf:
            path = self.root / "composer.md"
            path.write_text(self.composer)
            with patch.dict(os.environ, {"TMUX_PANE": PANE}):
                aside_editor.edit([str(path)])
            if self.late_draw:          # drawn only as the next key comes in
                self.handed, self.late_draw = path.read_text(), False
            else:
                self.show(path.read_text())
        elif key == "Enter" and self.composer and not self.slow:
            self.sent.append(self.composer)
            self.show("")

    def editor_tmux(self, *args, data=None):
        """tmux as ak's editor asks it, in the pane it runs in."""
        if args[0] == "show-options":
            said, self.ask = self.ask, None
            return f"{said}\n".encode() if said else b""
        if args[0] == "save-buffer":
            return self.buffers.get(args[-2])
        if args[0] == "load-buffer":
            self.buffers[args[-2]] = data
            return b""
        return self.tmux(*args)[1].encode()

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.tick()
        self.assertEqual((self.keys, self.sent), (["C-g", "Enter", "C-g"], [LINE]))
        self.assertEqual((self.composer, self.buffers, self.ask), (DRAFT, {}, None))
        self.assertTrue(self.told())

    def test_a_line_typed_while_the_owners_text_is_on_its_way_back_goes_in_alone(self):
        self.buffers, self.late_draw = {aside_editor.kept(PANE): DRAFT.encode()}, True
        self.show("")
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.composer, self.handed, self.buffers), ("", DRAFT, {}))
        self.wait_line()
        self.tick()
        # into a composer read empty too, the line goes in through the editor, never as keys
        self.assertEqual((self.keys, self.typed), (["C-g", "C-g", "Enter", "C-g"], []))
        self.assertEqual((self.sent, self.composer, self.buffers), ([LINE], DRAFT, {}))
        self.assertTrue(self.told())

    def test_a_line_its_seat_takes_late_is_told_once_the_owners_text_is_back(self):
        self.late(DRAFT)

    def test_text_put_back_that_reads_as_the_line_is_never_sent(self):
        self.late(LINE)

    def late(self, draft):
        """The owner's `draft` set aside for ak's line, which its seat takes a minute late."""
        self.show(draft)
        self.wait_line()
        self.slow = True
        self.tick()
        self.assertEqual((self.composer, self.told()), (LINE, False))
        # the seat takes it a minute on, and the tick brings the owner's text back first
        self.slow, self.sent = False, [LINE]
        self.show("")
        watch.time.time = lambda: NOW + 60
        watch.drafts_back(self.cfg, lambda _: None)
        self.tick()
        self.assertEqual((self.composer, self.sent), (draft, [LINE]))
        self.assertTrue(self.told())

    def test_text_typed_into_lately_or_in_a_seat_started_before_the_editor_is_left_alone(self):
        self.wait_line()
        self.untouched(watch.DRAFT_STILL - 10)
        self.tick()
        self.untouched(watch.DRAFT_STILL)
        self.launched = False
        self.tick()
        self.assertEqual((self.keys, self.typed, self.composer), ([], [], DRAFT))
        self.assertFalse(self.told())

    def test_text_taller_than_the_screen_read_is_set_aside_too(self):
        # Codex's rule finds a draft whose prompt row is above the read (`draft.rows`)
        prompt, tall = ((REPO / f"tests/fixtures/codex-{name}-pane.txt").read_text()
                        for name in ("prompt", "tall-line"))
        draft = tall[tall.index("› ") + 2:tall.index("\n\n  GPT-")].replace("\n  ", "\n")

        def show(composer):
            self.composer, self.free = composer, not composer
            self.pane = prompt.replace("› Ask Codex to do anything",
                                       "› " + composer.replace("\n", "\n  ")) if composer else prompt
        self.show = show
        show(draft)
        with patch.object(watch, "seat_model", return_value=("codex", "openai")):
            self.wait_line()
            self.tick()
        self.assertEqual((self.sent, self.composer), ([LINE], draft))
        self.assertTrue(self.told())

    def test_a_screen_with_no_composer_gets_no_editor_key(self):
        # Muse's resume pickers read as a draft its rule finds away from any composer
        with patch.object(watch, "seat_model", return_value=("muse", "openai")):
            for fixture in ("muse-resume-picker-pane.txt", "muse-title-resume-pane.txt"):
                self.pane, self.free = (REPO / "tests/fixtures" / fixture).read_text(), False
                self.wait_line()
                self.tick()
        self.assertEqual((self.keys, self.ask, self.told()), ([], None, False))

    def test_text_kept_comes_back_only_into_an_empty_composer_and_goes_with_its_pane(self):
        self.buffers = {aside_editor.kept(PANE): DRAFT.encode(), aside_editor.kept("%3"): b"x"}
        self.show("newer words")
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.keys, list(self.buffers)), ([], [aside_editor.kept(PANE)]))
        self.show("")
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.keys, self.composer, self.buffers), (["C-g"], DRAFT, {}))

    def test_an_ask_its_harness_never_acts_on_is_taken_back_and_asked_again(self):
        self.buffers, self.deaf = {aside_editor.kept(PANE): DRAFT.encode()}, True
        self.show("")
        self.wait_line()
        self.tick()
        watch.drafts_back(self.cfg, lambda _: None)
        # no ask left for the owner's own Ctrl-G to take, nor a receipt of a line never typed
        self.assertEqual((self.keys, self.ask, self.receipts()), (["C-g", "C-g"], None, []))
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): DRAFT.encode()})
        self.deaf = False
        self.tick()
        self.assertEqual((self.sent, self.composer, self.buffers), ([LINE], DRAFT, {}))
        self.assertTrue(self.told())


if __name__ == "__main__":
    unittest.main()

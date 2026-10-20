"""ak's line goes into a seat past the owner's unsent text through ak's editor, and that text
comes back once the line is sent, each step taken on the screen's word alone (19 Oct 2026).
Offline: fixtures.seats' seats, their tmux faked as a harness whose Ctrl-G hands its composer
to the real agentkit/aside_editor.py, and draws what that hands back a few reads late.
"""

from contextlib import contextmanager
import os
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, REPO, Seats
from agentkit import aside_editor, watch
from agentkit.watch import seat_editor

DRAFT = "and add these posts"
PANE = "%7"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.keys, self.sent, self.buffers, self.ask, self.late = [], [], {}, None, 0
        self.deaf, self.launched, self.tty = False, True, self.root / "tty"
        self.tty.write_text("")
        self.untouched(watch.DRAFT_STILL)
        for target, name, fake in ((aside_editor, "launched", lambda _pid, _tty: self.launched),
                                   (aside_editor, "_tmux", lambda *args, data=None:
                                    self.tmux(*args, data=data)[1].encode()),
                                   (watch, "seat_editor", seat_editor),
                                   (watch, "pane_text", self.read)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show(DRAFT)

    def untouched(self, seconds):
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def show(self, composer):
        self.composer, self.free = composer, not composer
        self.pane = self.base.replace(self.empty, f"❯ {composer}\n") if composer else self.base

    def read(self, *_args, **_kwargs):
        """The pane, drawing what the editor handed back on the third read after."""
        self.late -= 1
        if not self.late:
            self.show(self.handed)
        return self.pane

    def tmux(self, *args, data=None, **kwargs):
        """The seat's server, as ak and the editor in its pane ask it."""
        name = args[args.index("-b") + 1] if "-b" in args else None
        if args[0] == "display-message" and args[-1].startswith("#{pane_id}"):
            return 0, f"{PANE}\t4242\t{self.tty}"
        if args[0] == "show-options":       # read and cleared in one call
            said, self.ask = self.ask, None
            return 0, f"{said}\n" if said else ""
        if args[0] == "set-option":
            self.ask = None if "-pu" in args else args[-1]
        elif args[0] == "list-buffers":
            return 0, "".join(f"{each}\n" for each in self.buffers)
        elif args[0] == "save-buffer":
            return (0, self.buffers[name].decode()) if name in self.buffers else (1, "no buffer")
        elif args[0] == "load-buffer":
            self.buffers[name] = data
        elif args[0] == "delete-buffer":
            self.buffers.pop(name, None)
        elif args[0] == "send-keys" and "-l" in args:
            self.typed.append(args[-1])
            self.show(self.composer + args[-1])
        elif args[0] == "send-keys":
            for key in args[args.index("-t") + 2:]:
                self.press(key)
        else:
            return super().tmux(*args, **kwargs)
        return 0, ""

    def press(self, key):
        self.keys.append(key)
        if key == "C-g" and not self.deaf:
            path = self.root / "composer.md"
            path.write_text(self.composer)
            with patch.dict(os.environ, {"TMUX_PANE": PANE}):
                aside_editor.edit([str(path)])
            self.handed, self.late = path.read_text(), 3
        elif key == "Enter" and self.composer:
            self.sent.append(self.composer)
            self.show("")

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.deaf = True
        self.tick()
        # an edit never shown done leaves no ask for the owner's own Ctrl-G, nor a receipt
        self.assertEqual((self.composer, self.ask, self.receipts(), self.told()),
                         (DRAFT, None, [], False))
        self.deaf = False
        self.tick()
        self.assertEqual((self.keys, self.sent, self.composer, self.buffers, self.told()),
                         (["C-g", "C-g", "Enter", "C-g"], [LINE], DRAFT, {}, True))

    def test_text_the_line_ends_with_or_its_paste_fold_is_never_taken_for_the_line(self):
        long = "run acme finished FAIL: " + "a finding in detail " * 50
        for own, line, row in (("Decide the next\n  step.", LINE, None),
                               ("Private notes. " * 60, long, "❯ [Pasted text #1]\n")):
            with self.subTest(own=own[:15]):
                self.show(own)
                if row:
                    self.pane = self.base.replace(self.empty, row)
                self.deaf = True        # the editor never opens: the owner's text stays shown
                watch.type_at_prompt(self.seat, line, lambda _: None, cfg=self.cfg)
                self.assertEqual((self.sent, self.ask), ([], None))

    def test_text_not_back_with_its_line_comes_back_on_a_later_pass(self):
        self.wait_line()
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()                 # the line's Enter fails
        self.deaf = True
        self.tick()                     # its Enter, from its mark
        self.tick()                     # the editor never opens to bring the text back
        with patch.object(watch, "pane_unread", return_value=True):
            self.tick()                 # input the seat has not read yet
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], "", False))
        self.deaf = False
        self.tick()
        self.assertEqual((self.composer, self.buffers, self.told()), (DRAFT, {}, True))

    def test_no_line_goes_in_between_a_line_and_its_text_coming_back(self):
        self.wait_line()
        held, other = watch.seat_held, "The docs finished."

        @contextmanager
        def then_another(name):
            with held(name) as current:
                yield current
            if self.sent == [LINE]:
                watch.type_at_prompt(self.seat, other, lambda _: None, cfg=self.cfg)

        with patch.object(watch, "seat_held", then_another):
            self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE, other], DRAFT, True))

    def test_a_composer_holding_nothing_takes_the_line_as_keys(self):
        self.show("")
        self.wait_line()
        self.tick()
        self.assertEqual((self.keys, self.typed, self.buffers, self.told()),
                         (["Enter"], [LINE], {}, True))

    def test_text_typed_lately_mid_turn_or_in_a_seat_started_before_the_editor_stays(self):
        self.wait_line()
        self.untouched(watch.DRAFT_STILL - 10)
        self.tick()
        self.untouched(watch.DRAFT_STILL)
        self.pane = (REPO / "tests/fixtures/claude-draft-while-working-pane.txt").read_text()
        self.tick()
        self.show(DRAFT)
        self.launched = False
        self.tick()
        self.assertEqual((self.keys, self.typed, self.told()), ([], [], False))


if __name__ == "__main__":
    unittest.main()

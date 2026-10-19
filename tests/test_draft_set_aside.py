"""ak's line goes into a seat past the owner's unsent text through ak's editor, and that text
comes back once the composer reads empty, each step taken on the screen's word alone (19 Oct
2026).
Offline: fixtures.seats' seats, their tmux faked as a harness whose Ctrl-G hands its composer
to the real agentkit/aside_editor.py, and draws what that hands back a few reads late.
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
        self.keys, self.sent, self.buffers, self.ask, self.late = [], [], {}, None, 0
        self.deaf, self.slow, self.launched, self.tty = False, False, True, self.root / "tty"
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
        elif args[0] == "list-panes":
            return 0, f"{PANE}\t{SEAT}"
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
        elif key == "Enter" and self.composer and not self.slow:
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

    def test_a_line_its_seat_takes_late_is_told_once_the_owners_text_is_back(self):
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
        self.assertEqual((self.composer, self.sent, self.told()), (DRAFT, [LINE], True))

    def test_a_draft_its_harness_never_hands_to_an_editor_holds_the_line_back(self):
        # Grok 1.0.46 refuses it for a draft holding a pasted chip, saying so in its transcript
        chip = (REPO / "tests/fixtures/grokbuild-pasted-chip-pane.txt").read_text()
        with patch.object(watch, "seat_model", return_value=("grokbuild", "xai")):
            where = watch.seat_editor(self.seat, self.cfg)
            plain = chip.replace("Pasted: 40 lines", "and more")
            for self.pane, standing in ((chip, False), (plain, True)):
                self.assertEqual(watch.draft_standing(self.seat, where, self.cfg), standing)

    def test_text_kept_comes_back_only_into_an_empty_composer_and_goes_with_its_pane(self):
        self.buffers = {aside_editor.kept(PANE): DRAFT.encode(), aside_editor.kept("%3"): b"x"}
        self.show("newer words")
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.keys, list(self.buffers)), ([], [aside_editor.kept(PANE)]))
        self.show("")
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.keys, self.composer, self.buffers), (["C-g"], DRAFT, {}))

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
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], draft, True))

    def test_a_screen_with_no_composer_gets_no_editor_key(self):
        # Muse's resume pickers read as a draft its rule finds away from any composer
        with patch.object(watch, "seat_model", return_value=("muse", "openai")):
            for fixture in ("muse-resume-picker-pane.txt", "muse-title-resume-pane.txt"):
                self.pane, self.free = (REPO / "tests/fixtures" / fixture).read_text(), False
                self.wait_line()
                self.tick()
        self.assertEqual((self.keys, self.ask, self.told()), ([], None, False))


if __name__ == "__main__":
    unittest.main()

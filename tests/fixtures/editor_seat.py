"""fixtures.seats' seat, launched with ak's editor: its tmux faked as a harness whose Ctrl-G hands
its composer to the real agentkit/aside_editor.py, takes what that hands back at once and draws
it a few reads late, and whose Enter sends what its composer holds, one composer for any pane
ak names; a paste lands in it whole.  Whether it hears the key (`deaf`), the seat's launch, the panes of its session
(PANE the one selected), unread input and when its terminal last took keys are the test's to
set."""

import os
from pathlib import Path
from unittest.mock import patch

from fixtures.seats import NOW, PANE, Seats
from agentkit import aside_editor, watch


class EditorSeat(Seats):
    def setUp(self):
        super().setUp()
        self.keys, self.sent, self.buffers, self.ask, self.late = [], [], {}, None, 0
        self.pasted = []
        self.opened = []        # the owner's own editor, opened where ak asked nothing
        self.deaf, self.launched, self.tty, self.panes = False, True, self.root / "tty", [PANE]
        self.unread = False
        self.tty.write_text("")
        for target, name, fake in ((aside_editor, "launched", lambda _pid, _tty: self.launched),
                                   (aside_editor, "_tmux", lambda *args, data=None:
                                    self.editor_tmux(*args, data=data)),
                                   (aside_editor.os, "execvp",
                                    lambda *argv: self.opened.append(argv)),
                                   (watch, "pane_text", self.read),
                                   (watch, "pane_unread", lambda _session: self.unread)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show("")

    def untouched(self, seconds):
        """The seat's terminal, last given keys that long ago."""
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def show(self, composer):
        """The composer holding that text, drawn at once."""
        self.composer, self.late = composer, 0
        self.draw(composer)

    def draw(self, composer):
        self.free = not composer        # a harness reads a composer holding text as no prompt
        self.pane = self.base.replace(self.empty, f"❯ {composer}\n") if composer else self.base

    def read(self, *_args, **_kwargs):
        """The pane, drawing what the editor handed back on the third read after."""
        self.late -= 1
        if not self.late:
            self.draw(self.composer)
        return self.pane

    def editor_tmux(self, *args, data=None):
        rc, out = self.tmux(*args, data=data)
        return out.encode() if rc == 0 else None

    def tmux(self, *args, data=None, **kwargs):
        """The seat's server, as ak and the editor in its pane ask it."""
        name = args[args.index("-b") + 1] if "-b" in args else None
        target = args[args.index("-t") + 1] if "-t" in args else ""
        pane = target if target.startswith("%") else PANE
        if args[0] == "display-message" and args[-1].startswith("#{pane_id}\t"):
            return 0, f"{pane}\t4242\t{self.tty}"
        if args[0] == "show-options":
            said = self.ask
            if ";" in args:                 # the editor's: read and cleared in one call
                self.ask = None
            return 0, f"{said}\n" if said else ""
        if args[0] == "set-option":
            self.ask = None if "-pu" in args else args[-1]
        elif args[0] == "list-panes":
            return 0, "".join(f"{each}\n" for each in self.panes)
        elif args[0] == "list-buffers":
            return 0, "".join(f"{each}\n" for each in self.buffers)
        elif args[0] == "save-buffer":
            return (0, self.buffers[name].decode()) if name in self.buffers else (1, "no buffer")
        elif args[0] == "load-buffer":
            self.buffers[name] = data if data is not None else Path(args[-1]).read_bytes()
        elif args[0] == "set-buffer":
            self.buffers[name] = args[-1].encode()
        elif args[0] == "paste-buffer":
            self.pasted.append(self.buffers[name].decode())
            self.show(self.composer + (self.buffers.pop(name) if "-d" in args
                                       else self.buffers[name]).decode())
        elif args[0] == "delete-buffer":
            self.buffers.pop(name, None)
        elif args[0] == "send-keys" and "-l" in args:
            self.typed.append(args[-1])
            self.show(self.composer + args[-1])
        elif args[0] == "send-keys":
            for key in args[args.index("-t") + 2:]:
                self.press(key, pane)
        else:
            return super().tmux(*args, **kwargs)
        return 0, ""

    def press(self, key, pane=PANE):
        self.keys.append(key)
        if key == "C-g" and not self.deaf:
            path = self.root / "composer.md"
            path.write_text(self.composer)
            with patch.dict(os.environ, {"TMUX_PANE": pane}):
                aside_editor.edit([str(path)])
            self.composer, self.late = path.read_text(), 3
        elif key == "Enter" and self.composer:
            self.sent.append(self.composer)
            self.show("")

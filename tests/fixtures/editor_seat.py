"""fixtures.seats' seat, launched with ak's editor: its tmux faked as a harness whose Ctrl-G hands
its composer to the real agentkit/aside_editor.py, and draws what that hands back a few reads
late (`late`), and whose Enter sends what its composer holds as a prompt.  Whether it hears the
key (`deaf`) and the seat's launch are the test's to set."""

import json
import os
from unittest.mock import patch

from fixtures.seats import Seats
from agentkit import aside_editor, config, watch
from agentkit.watch import seat_editor

PANE = "%7"


class EditorSeat(Seats):
    def setUp(self):
        super().setUp()
        self.keys, self.sent, self.buffers, self.ask, self.late = [], [], {}, None, 0
        self.deaf, self.launched, self.tty = False, True, self.root / "tty"
        self.tty.write_text("")
        for target, name, fake in ((aside_editor, "launched", lambda _pid, _tty: self.launched),
                                   (aside_editor, "_tmux", lambda *args, data=None:
                                    self.tmux(*args, data=data)[1].encode()),
                                   (watch, "seat_editor", seat_editor),
                                   (watch, "pane_text", self.read)):
            patcher = patch.object(target, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show("")

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
            # the seat's prompt hook stamps the moment its prompt went in
            config.stop_path(self.seat["name"]).write_text(json.dumps({"turn": watch.time.time()}))

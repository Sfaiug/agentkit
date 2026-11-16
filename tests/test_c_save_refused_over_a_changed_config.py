"""A key on `c` that saves, read after another process changed config.toml since `c` read it,
writes nothing: `c` saves the config it holds whole, so it would take out what the other wrote,
a model `watch.follow_model` just added.  The screen goes on with the file's config and says
the key was not taken; the same key again, the file unchanged since, is taken.

Offline: a throwaway HOME, `c` opened over no seat with its keys fed in, the other save made
in the read of the first Space, after `c` drew.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal, update, usage  # noqa: E402
from agentkit.terminal import Key  # noqa: E402

# the model another process adds, as watch.follow_model adds one a seat picked
ADDED = {"harness": "claude", "model": "claude-acme-1", "effort": "high", "provider": "anthropic"}


class Keyboard:
    def take(self):
        return True


class SaveRefusedOverAChangedConfig(Sandbox):
    def setUp(self):
        super().setUp()
        config.save(self.cfg)
        for target, name, value in ((update, "agentkit_version", lambda: "abc1234"),
                                    (usage, "collect", lambda *_a, **_kw: usage.Readings({}))):
            self.stack.enter_context(patch.object(target, name, side_effect=value))

    def keyed(self, *reads):
        """`c` opened over no seat, each of `reads` answering a read of a key in turn, then Esc;
        what it drew, as it draws, in `drawn`."""
        self.drawn, reads = io.StringIO(), iter((*reads, lambda: Key("esc")))
        with patch.object(terminal, "read_key", side_effect=lambda *_a, **_kw: next(reads)()), \
                redirect_stdout(self.drawn):
            menu.show_config(False, Keyboard(), None)
        return terminal.plain(self.drawn.getvalue())

    def test_a_space_over_a_config_changed_since_writes_nothing(self):
        seen = {}
        orchestrator = config.load()["defaults"]["orchestrator"]
        self.assertNotEqual(orchestrator, "fable")      # the Space would move it

        def added():                # another process's save, after `c` drew
            seen["added"] = config.add_model(config.load(), dict(ADDED), "Acme 1")
            return Key("space")     # on the first model's orchestrator mark: fable's

        def refused():              # what the Space left, before the next is read
            seen["refused"] = config.load(), terminal.plain(self.drawn.getvalue())
            return Key("space")
        self.keyed(added, refused)

        cfg, screen = seen["refused"]
        self.assertEqual(cfg["models"][seen["added"]]["model"], ADDED["model"])
        self.assertEqual(cfg["defaults"]["orchestrator"], orchestrator)
        self.assertIn(menu.CHANGED, screen)
        cfg = config.load()                 # the second Space, the file unchanged since
        self.assertEqual(cfg["defaults"]["orchestrator"], "fable")
        self.assertEqual(cfg["models"][seen["added"]]["model"], ADDED["model"])

    def test_no_space_writes_over_a_changed_config_that_will_not_load(self):
        path = config.HOME / config.CONFIG_NAME
        broken = "companies = 3\n" + path.read_text()      # a hand edit load refuses

        def edited():               # after `c` drew
            new = path.with_name("config.toml.new")
            new.write_text(broken)
            new.replace(path)
            return Key("space")

        def again():                # `c` tried the file again, and it still will not load
            self.assertEqual(path.read_text(), broken)
            return Key("space")
        self.assertIn(menu.CHANGED, self.keyed(edited, again))
        self.assertEqual(path.read_text(), broken)

if __name__ == "__main__":
    unittest.main()

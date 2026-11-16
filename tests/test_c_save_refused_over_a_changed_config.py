"""A key on `c` that saves, read after another process changed config.toml since `c` read it,
writes nothing: `c` saves the config it holds whole, so it would take out what the other wrote,
a model `watch.follow_model` just added.  The screen goes on with the file's config and says
the key was not taken; the same key again, the file unchanged since, is taken.  Subscriptions,
opened from a meter as the ak screen opens it, holds the file it read as it opened as `c` does,
a file gone since its caller read it read too: config.load's shipped defaults.

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

    def keyed(self, *reads, opens=lambda: menu.show_config(False, Keyboard(), None)):
        """`c` opened over no seat, or what `opens` opens, each of `reads` answering a read of a
        key in turn, then Esc; what it drew, as it draws, in `drawn`."""
        self.drawn, reads = io.StringIO(), iter((*reads, lambda: Key("esc")))
        with patch.object(terminal, "read_key", side_effect=lambda *_a, **_kw: next(reads)()), \
                redirect_stdout(self.drawn):
            opens()
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

    def test_a_remove_on_subscriptions_opened_from_a_meter_writes_nothing_over_a_change(self):
        added, said = [], []

        def remove():               # another process's save, then Enter on `− remove`
            added.append(config.add_model(config.load(), dict(ADDED), "Acme 1"))
            return Key("enter")
        # the ak screen's first meter, which offers nothing: its row on Subscriptions
        label = menu.usage_rows(self.cfg)[0][1]
        with patch.object(terminal, "confirm", return_value=True):
            self.keyed(lambda: Key("right"), remove, opens=lambda: said.append(
                menu.meter_acts(self.cfg, Keyboard(), 1, label)))
        self.assertEqual(said, [menu.CHANGED])
        cfg = config.load()
        self.assertEqual(cfg["models"][added[0]]["model"], ADDED["model"])
        self.assertEqual(cfg["providers"].keys(), self.cfg["providers"].keys())

    def test_subscriptions_reads_config_toml_gone_since_its_caller_read_it(self):
        stale = config.load()
        stale["providers"] = {name: stale["providers"][name] for name in ("anthropic", "openai")}
        config.save(stale)
        (config.HOME / config.CONFIG_NAME).unlink()     # another process, after the caller read
        shown = []

        def page(_title, _body, _places, rows, here, top, *_a, **_kw):
            shown.append(len(rows) - 1)                 # its rows, `+ add` aside
            return "back", here, None, top
        with patch.object(menu, "matrix_key", side_effect=page):
            menu.config_subscriptions(stale, Keyboard())
        self.assertEqual(shown, [len(menu.usage_rows(config.load()))])
        self.assertGreater(shown[0], len(menu.usage_rows(stale)))

if __name__ == "__main__":
    unittest.main()

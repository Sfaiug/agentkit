"""`n` checks a new name against the listing the menu has in hand, and asks no harness to
reconcile a record for it.

The owner's report (18 Oct 2026): `n` took a third of a second before its name question.  The
name check listed the seats again, and read every record through its harness's reconcile only
to learn which records there are.  Offline: a temporary HOME, no tmux, no harness.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, orch  # noqa: E402


def asked(*_args, **_kw):
    raise AssertionError("asked again")


class InHand(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ("fix-api", "ship-docs"):
            config.save_session(self.cfg, name, "fable", ["opus"], {"cwd": str(self.root)})
        config.rename_session("ship-docs", "docs")     # its old name still leads somewhere
        for name in ("listing", "seat_plugin"):
            self.stack.enter_context(patch.object(orch, name, asked))
        self.stack.enter_context(patch.object(orch, "held_names", return_value={"acme"}))

    def test_the_names_taken_are_read_off_the_listing_in_hand(self):
        found = [{"name": "fix-api"}, {"name": "docs"}]
        self.assertEqual(orch.taken_names(found), {"fix-api", "docs", "ship-docs", "acme"})

    def test_n_asks_its_name_against_the_menus_listing(self):
        def ask_name(taken, **_kw):
            self.assertEqual(taken, {"fix-api", "ship-docs", "acme"})
            return orch.BACK

        with patch.object(orch, "ask_name", ask_name), patch.object(menu.terminal, "frame"):
            self.assertIsNone(menu.new_session(self.cfg, True, found=[{"name": "fix-api"}]))


if __name__ == "__main__":
    unittest.main()

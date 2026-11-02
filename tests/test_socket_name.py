"""The account's own home keeps the seats' server, by whichever path HOME spells it.

tests/test_key_a_moved_home_has_its_own_tmux_server.py holds the moved HOME from outside, where
HOME can never be the account's own without reaching the owner's real ~/.agentkit.  Here the
account's entry is faked instead.
"""

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, orch


class SocketName(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.account = Path(scratch.name).resolve() / "acme"
        self.account.mkdir()
        self.link = self.account.with_name("link")
        self.link.symlink_to(self.account)

    def name(self, home, entry=None, socket=None):
        """The server named with HOME at `home` and the account's entry being `entry`."""
        answer = {"side_effect": KeyError} if entry is None else {
            "return_value": types.SimpleNamespace(pw_dir=str(entry))}
        env = {"HOME": str(home), orch.SOCKET_ENV: socket or ""}
        with patch.dict(os.environ, env), patch.object(orch.pwd, "getpwuid", **answer), \
                patch.object(config, "HOME", Path(home) / ".agentkit"):
            return orch.socket_name()

    def test_the_accounts_own_home_keeps_the_seats_server(self):
        self.assertEqual(self.name(self.account, self.account), "agentkit")
        self.assertEqual(self.name(self.link, self.account), "agentkit")
        self.assertEqual(self.name(self.account, self.link), "agentkit")

    def test_any_other_home_has_its_own_and_one_home_one_name(self):
        other = self.name(self.account, self.account.parent)
        self.assertRegex(other, r"\Aagentkit-[0-9a-f]{8}\Z")
        self.assertEqual(self.name(self.link, self.account.parent), other)

    def test_a_uid_with_no_entry_has_no_home_to_be_and_does_not_fail(self):
        self.assertRegex(self.name(self.account), r"\Aagentkit-[0-9a-f]{8}\Z")

    def test_a_home_whose_name_is_not_utf8_has_its_own_too(self):
        home = self.account / os.fsdecode(b"home-\xff")
        self.assertRegex(self.name(home, self.account), r"\Aagentkit-[0-9a-f]{8}\Z")

    def test_the_socket_variable_wins_over_both(self):
        self.assertEqual(self.name(self.account, self.account, socket="x"), "x")
        self.assertEqual(self.name(self.account, self.account.parent, socket="x"), "x")


if __name__ == "__main__":
    unittest.main()

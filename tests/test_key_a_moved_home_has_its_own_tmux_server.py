"""A moved HOME reaches a tmux server of its own, never the seats'.

`agentkit` is the seats' server only under the account's own home; each other HOME names its own,
and AGENTKIT_TMUX_SOCKET wins over both.  Black-box: `ak orch list` runs from outside through
tests/fixtures/akbin.py under two scratch HOMEs, with a `tmux` first on PATH that records its
arguments and answers nothing, so no server is ever started or reached.  This test fails against
`/bin/false`.
"""

import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home


def servers(home, socket, **env):
    """Every server the seats' listing named after `-L`, with the variable set to `socket`."""
    home.fake("tmux", LOG.format(python=shlex.quote(sys.executable),
                                 log=shlex.quote(str(home.log("tmux")))))
    done = home.ak("orch", "list", env={"AGENTKIT_TMUX_SOCKET": socket, **env})
    assert done.code == 0, done.err
    return {call[call.index("-L") + 1] for call in home.calls("tmux") if "-L" in call}


class MovedHome(unittest.TestCase):
    def setUp(self):
        self.homes = Home(), Home()
        for home in self.homes:
            self.addCleanup(home.close)

    def test_each_scratch_home_names_a_server_of_its_own(self):
        first, second = (servers(home, None) for home in self.homes)
        self.assertEqual(len(first), 1, first)
        self.assertEqual(len(second), 1, second)
        self.assertNotEqual(first, second)
        self.assertNotIn("agentkit", first | second)

    def test_a_home_whose_name_is_not_utf8_names_one_too(self):
        home = self.homes[0]
        named = home.root / os.fsdecode(b"home-\xff")
        named.mkdir()
        found = servers(home, None, HOME=str(named))
        self.assertEqual(len(found), 1, found)
        self.assertNotIn("agentkit", found)

    def test_the_socket_variable_wins(self):
        for home in self.homes:
            self.assertEqual(servers(home, "x"), {"x"})


if __name__ == "__main__":
    unittest.main()

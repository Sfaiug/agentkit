"""Bare `ak`, or a first word starting with `-`, is the menu; on a client it is an ssh hop.

A client records the server's ssh alias in ~/.agentkit/state/server, and its `ak` is then
`ssh -t ALIAS ak --client`, which is how a person's `ak` there reaches the server's seats, and
`--dry-run` names the hop without making it.  The menu without an alias wants a terminal for its
keys and is not judged here.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home

ALIAS = "acme-box"
HOP = ["-t", ALIAS, "ak", "--client"]
# ak's own exits are 0, 1, 2 and 130, so a 7 can only be ssh's, handed on.
SSH = LOG + "exit 7\n"


class RemoteHop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/state/server", f"{ALIAS}\n")
        cls.home.fake("ssh", SSH.format(python=shlex.quote(sys.executable),
                                        log=shlex.quote(str(cls.home.log("ssh")))))

    def test_a_dry_run_names_the_ssh_hop_and_connects_nowhere(self):
        before, hops = self.home.tree(), len(self.home.calls("ssh"))
        for args in (("--dry-run",), ("attach", "--dry-run"), ("--dry-run", "--dry-run")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(done.out, f"would run ssh -t {ALIAS} ak --client\n")
        self.assertEqual(len(self.home.calls("ssh")), hops)
        self.assertEqual(self.home.tree(), before)

    def test_bare_ak_hops_to_the_server_and_exits_as_ssh_did(self):
        for args in ((), ("attach",)):
            with self.subTest(args=args):
                hops = len(self.home.calls("ssh"))
                done = self.home.ak(*args)
                self.assertEqual(done.code, 7, done.err)
                self.assertEqual(self.home.calls("ssh")[hops:], [HOP])

    def test_help_after_a_dash_led_word_is_the_top_level_help(self):
        top = self.home.ak("--help")
        self.assertEqual(top.code, 0, top.err)
        hops = len(self.home.calls("ssh"))
        for args in (("--client", "--help"), ("--overlay", "--dry-run", "-h"), ("-h",)):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(done.out, top.out)
        self.assertEqual(len(self.home.calls("ssh")), hops)


if __name__ == "__main__":
    unittest.main()

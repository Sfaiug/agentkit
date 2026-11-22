"""`ak --client` on a machine that is itself a home's client goes on to that home, once.

When a standby takes over, the old home becomes the new home's client while the owner's laptop is
still the old home's: its `ak` runs `ssh -t OLD ak --client`, and there the menu goes on with
`ssh -t NEW ak --client --client`, exiting as ssh did; `--dry-run` names that hop without making
it.  `--client` twice is the second hop saying it is one: a client goes no further, prints one
line naming its home and exits 1, so two records naming each other never chain ssh sessions.  On
a machine that is no client, `--client` twice is `--client` once.  A client's `ak` without
`--client` hops with one, as tests/test_key_dash_led_attach.py holds.  Black-box: the program
`AK_BIN` names runs on Homes of tests/fixtures/akbin.py, with a fake ssh that logs its arguments.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home

HOME = "acme-mini"


class AClientsMenuHopsOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Home()
        cls.addClassCleanup(cls.client.close)
        cls.client.write(".agentkit/state/server", f"{HOME}\n")

    def ssh_exits(self, code):
        self.client.fake("ssh", (LOG + f"exit {code}\n").format(
            python=shlex.quote(sys.executable), log=shlex.quote(str(self.client.log("ssh")))))

    def ak(self, *args):
        """`ak args` on the client, and each argv ssh was called with meanwhile."""
        before = len(self.client.calls("ssh"))
        done = self.client.ak(*args)
        return done, self.client.calls("ssh")[before:]

    def test_once_it_hops_on_saying_it_is_the_second_and_exits_as_ssh_did(self):
        # ak's own exits are 0, 1, 2 and 130, so a 7 can only be ssh's, handed on
        for code in (0, 7):
            with self.subTest(code=code):
                self.ssh_exits(code)
                done, hops = self.ak("--client")
                self.assertEqual(done.code, code, done)
                self.assertEqual(hops, [["-t", HOME, "ak", "--client", "--client"]])

    def test_a_dry_run_names_that_hop_and_makes_none(self):
        self.ssh_exits(0)
        done, hops = self.ak("--client", "--dry-run")
        self.assertEqual(done.code, 0, done)
        self.assertEqual(hops, [])
        self.assertIn(f"ssh -t {HOME} ak --client --client", done.out)

    def test_twice_it_goes_no_further_in_one_line_naming_its_home(self):
        self.ssh_exits(0)
        done, hops = self.ak("--client", "--client")
        self.assertEqual(done.code, 1, done)
        self.assertEqual(hops, [])
        said = (done.out + done.err).splitlines()
        self.assertEqual(len(said), 1, done)
        self.assertIn(HOME, said[0])

    def test_without_client_it_hops_with_one_as_today(self):
        self.ssh_exits(0)
        done, hops = self.ak()
        self.assertEqual(done.code, 0, done)
        self.assertEqual(hops, [["-t", HOME, "ak", "--client"]])


class AHomeThatIsNoClient(unittest.TestCase):
    def test_client_twice_is_client_once(self):
        with Home() as home:
            once = home.ak("--client", "--dry-run")
            twice = home.ak("--client", "--client", "--dry-run")
            self.assertEqual(twice.code, once.code, (once, twice))
            self.assertEqual(home.calls("ssh"), [])


if __name__ == "__main__":
    unittest.main()

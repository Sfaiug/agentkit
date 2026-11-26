"""A server install on a system ak cannot set up stops at its first line, having written nothing.

ak sets a server's packages up with apt-get, and a Mac's server is a Linux machine ak makes only
on Apple silicon, a shell under Rosetta's too.  Anywhere else a server install, rather than
install half and fail later, far from the cause, says first, on stderr, that ak installs on
Debian, Ubuntu and a Mac with Apple silicon, and what this machine is by `uname -s` and
`uname -m`, and exits 1, HOME as empty as it was.  Black-box: install.sh of the checkout `AK_BIN`
names runs from outside in an empty HOME that is the account's own (tests/fixtures/installer.py),
on a PATH of the host's own tools but `apt-get`, with a fake `uname` and `sysctl`.
"""

import os
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

LINUX = ("Linux", os.uname().machine)
INTEL_MAC = ("Darwin", "x86_64")
# what an Apple silicon Mac's sysctl says to a shell under Rosetta, whose `uname -m` is x86_64
APPLE_SILICON = '#!/bin/sh\n[ "$*" = "-n hw.optional.arm64" ] && echo 1\n'


class Refused(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        installer.prepare(home)
        installer.own_home(home)
        installer.without(home, "apt-get")      # a Debian host's too
        home.refuse("sysctl")                   # an Intel Mac's knows no hw.optional.arm64
        shutil.rmtree(home.path)
        home.path.mkdir()

    def install(self, system, machine):
        self.home.fake("uname",
                       f"#!/bin/sh\ncase $1 in -m) echo {machine} ;; *) echo {system} ;; esac\n")
        return installer.run(self.home)

    def refused(self, system, machine):
        done = self.install(system, machine)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(done.out, "")
        first = done.err.partition("\n")[0]
        for named in ("Debian", "Ubuntu", "Mac with Apple silicon", f"{system} {machine}"):
            self.assertIn(named, first)
        self.assertEqual(list(self.home.path.iterdir()), [])

    def test_a_linux_without_apt_get_is_refused_first_with_home_untouched(self):
        self.refused(*LINUX)

    def test_so_is_a_linux_whose_apt_get_on_path_is_no_program(self):
        (self.home.bin / "apt-get").touch(mode=0o644)
        self.refused(*LINUX)

    def test_so_is_an_intel_mac(self):
        self.refused(*INTEL_MAC)

    @unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")
    def test_with_apt_get_the_same_install_goes_on_past_that_line(self):
        self.home.refuse("apt-get")
        done = self.install(*LINUX)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue((self.home.path / ".agentkit" / "config.toml").is_file())

    def test_an_apple_silicon_mac_goes_on_past_it_from_a_shell_under_rosetta_too(self):
        self.home.fake("sysctl", APPLE_SILICON)
        done = self.install(*INTEL_MAC)
        self.assertTrue((self.home.path / ".agentkit").is_dir(), done.out + done.err)


if __name__ == "__main__":
    unittest.main()

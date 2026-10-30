"""On a Mac that gets ak's Linux machine, the install keeps the Mac up for it: on power the Mac
never sleeps, though its display may, and it starts again by itself when power comes back after
a cut.  Both are macOS's own power settings, which hold across restarts; the install sets only
what is not so yet, through sudo, so a second install changes nothing.  With FileVault on, a Mac
that starts again waits for its password before anything of it runs, ak's machine included, and
the install says so in one line.  Black-box on the fake Mac of
tests/test_key_install_mac_linux_machine.py, whose `pmset`, `fdesetup` and `sudo` are fakes.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_install_mac_linux_machine import MINI, Mac

# A laptop as it ships: on battery its display sleeps sooner, and the Mac once its display does.
LAPTOP = {"Battery Power": {"sleep": 1, "displaysleep": 2}, **MINI}


def sets(mac):
    return [call for call in mac.home.calls("pmset") if call[0] != "-g"]


def lines(mac, done):
    return done.out.replace(str(mac.home.root), "<root>").splitlines()


class FreshMac(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mac = mac = Mac(power=LAPTOP)
        cls.addClassCleanup(mac.close)
        cls.out = lines(mac, mac.install())
        cls.first = mac.power()
        cls.set = sets(mac)
        mac.install()

    def test_on_power_it_never_sleeps_though_its_display_may(self):
        self.assertEqual(self.first["AC Power"]["sleep"], 0)
        self.assertEqual(self.first["AC Power"]["displaysleep"], 10)

    def test_it_starts_again_by_itself_after_a_power_cut(self):
        self.assertEqual(self.first["AC Power"]["autorestart"], 1)

    def test_on_battery_it_sleeps_as_it_did(self):
        self.assertEqual(self.first["Battery Power"], LAPTOP["Battery Power"])

    def test_a_second_install_changes_nothing_already_right(self):
        self.assertEqual(self.mac.power(), self.first)
        self.assertEqual(sets(self.mac), self.set)

    def test_with_filevault_on_one_line_says_ak_s_machine_waits_for_the_password(self):
        mac = Mac(power=LAPTOP, filevault=True)
        self.addCleanup(mac.close)
        out = lines(mac, mac.install())
        self.assertEqual([line for line in self.out if line not in out], [])
        [line] = [line for line in out if line not in self.out]
        self.assertIn("FileVault", line)
        self.assertIn("password", line)


if __name__ == "__main__":
    unittest.main()

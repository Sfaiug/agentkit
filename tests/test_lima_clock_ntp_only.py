"""On a Mac's Linux machine the clock is NTP's alone: Lima's guest agent may not set it."""
import os
import sys
import unittest
from unittest.mock import patch
from test_slice import Installer
from test_user_unit_ceiling import SUDO


class LimaClock(Installer):
    SECTION, NEXT = "# --- (g2c) the clock is NTP's alone", "# --- (h) a new phone key"  # (g3)'s tests run too

    def setUp(self):
        super().setUp()
        (self.bin / "sudo").write_text(SUDO.format(python=sys.executable))
        (self.bin / "sudo").chmod(0o755)
        self.unit = self.root / "etc-systemd/lima-guestagent.service"
        self.stack.enter_context(patch.dict(os.environ, {"AK_SYSTEMD_SYSTEM": str(self.unit.parent), "AK_UNIT_SUDO": "1"}))

    def restarts(self):  # of the guest agent, after one more install
        result = self.install(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.commands("systemctl").count(["systemctl", "try-restart", "lima-guestagent"])

    def test_a_lima_machine_takes_the_clock_from_its_guest_agent_once(self):
        self.assertEqual(self.restarts(), 0)  # no Lima here: nothing in force
        self.unit.parent.mkdir()
        self.unit.write_text("[Service]\n")
        self.assertEqual(self.restarts(), 1)
        dropin = self.unit.parent / "lima-guestagent.service.d/agentkit-clock.conf"
        self.assertIn("[Service]\nProtectClock=yes\n", dropin.read_text())
        self.assertEqual(self.restarts(), 1)  # in force already: nothing written or restarted


if __name__ == "__main__":
    unittest.main()

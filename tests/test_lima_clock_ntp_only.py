"""On a Mac's Linux machine the clock is NTP's alone: Lima's guest agent may not set it."""
import os
import sys
import unittest
from unittest.mock import patch
from test_slice import Installer
from test_user_unit_ceiling import SUDO

HOLDS_CLOCK = "CapBnd:\t000001ffffffffff\n"  # CAP_SYS_TIME, bit 25, still in the bounding set

# systemd and the kernel, as far as the clock goes: a reload reads the drop-in, and a restart puts the
# agent (pid 7) under it, its bounding set without CAP_SYS_TIME only where ProtectClock is loaded.
# Every call then goes on to test_slice's spy, which records it.
SYSTEMD = '''#!{python}
import os, pathlib, sys
args, proc = sys.argv[1:], pathlib.Path(os.environ["AK_PROC"])
dropin = pathlib.Path(os.environ["AK_SYSTEMD_SYSTEM"]) / "lima-guestagent.service.d/agentkit-clock.conf"
if args == ["show", "-p", "MainPID", "--value", "lima-guestagent"]:
    print(7)
    sys.exit()
if args == ["daemon-reload"]:
    (proc / "loaded").write_text(dropin.read_text() if dropin.exists() else "")
if args == ["try-restart", "lima-guestagent"]:
    loaded = (proc / "loaded").read_text() if (proc / "loaded").exists() else ""
    (proc / "7/status").write_text("CapBnd:\\t000001fffdffffff\\n" if "ProtectClock=yes" in loaded else {holds!r})
os.execv({spy!r}, [{spy!r}, *args])
'''


class LimaClock(Installer):
    SECTION, NEXT = "# --- (g2c) the clock is NTP's alone", "# --- (h) a new phone key"  # (g3)'s tests run too

    def setUp(self):
        super().setUp()
        (self.bin / "sudo").write_text(SUDO.format(python=sys.executable))
        (self.bin / "sudo").chmod(0o755)
        spy = self.root / "spy/systemctl"
        spy.parent.mkdir()
        (self.bin / "systemctl").rename(spy)
        (self.bin / "systemctl").write_text(SYSTEMD.format(python=sys.executable, spy=str(spy), holds=HOLDS_CLOCK))
        (self.bin / "systemctl").chmod(0o755)
        self.proc = self.root / "proc"
        self.agent = self.proc / "7/status"
        self.agent.parent.mkdir(parents=True)
        self.agent.write_text(HOLDS_CLOCK)
        self.unit = self.root / "etc-systemd/lima-guestagent.service"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_SYSTEMD_SYSTEM": str(self.unit.parent), "AK_PROC": str(self.proc), "AK_UNIT_SUDO": "1"}))

    def restarts(self):  # of the guest agent, after one more install
        result = self.install(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.commands("systemctl").count(["systemctl", "try-restart", "lima-guestagent"])

    def lima(self):
        self.unit.parent.mkdir()
        self.unit.write_text("[Service]\n")

    def test_a_lima_machine_takes_the_clock_from_its_guest_agent_once(self):
        self.assertEqual(self.restarts(), 0)  # no Lima here: nothing in force
        self.lima()
        self.assertEqual(self.restarts(), 1)
        dropin = self.unit.parent / "lima-guestagent.service.d/agentkit-clock.conf"
        self.assertIn("[Service]\nProtectClock=yes\n", dropin.read_text())
        self.assertEqual(self.restarts(), 1)  # in force already: nothing written or restarted

    def test_an_agent_still_holding_the_clock_is_put_under_the_drop_in_again(self):
        self.lima()
        self.assertEqual(self.restarts(), 1)
        # what a reload or restart that failed or was cut short leaves: the drop-in written, the agent as it was
        (self.proc / "loaded").unlink()
        self.agent.write_text(HOLDS_CLOCK)
        self.assertEqual(self.restarts(), 2)
        self.assertEqual(self.restarts(), 2)


if __name__ == "__main__":
    unittest.main()

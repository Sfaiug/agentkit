"""On a Mac's Linux machine the clock is NTP's alone: Lima's guest agent may not set it.

Offline: the `Installer` fakes from `test_slice` and the `sudo` from `test_user_unit_ceiling`, plus
a systemd and kernel of this test's own, as far as the clock goes: a reload reads the drop-in, and a
restart puts the agent (pid 7) under it, without CAP_SYS_TIME only where it holds ProtectClock=yes.
"""
import os
import sys
import unittest
from unittest.mock import patch
import test_slice
from test_user_unit_ceiling import SUDO

HOLDS_CLOCK = "CapBnd:\t000001ffffffffff\n"  # CAP_SYS_TIME, bit 25, still in the bounding set
RESTRICTED = "CapBnd:\t000001fffdffffff\n"

# The step that AK_SYSTEMD_FAILS names fails; every call that does not goes on to test_slice's spy.
SYSTEMD = '''#!{python}
import os, pathlib, sys
args, proc = sys.argv[1:], pathlib.Path(os.environ["AK_PROC"])
dropin = pathlib.Path(os.environ["AK_SYSTEMD_SYSTEM"]) / "lima-guestagent.service.d/agentkit-clock.conf"
if args[:1] == [os.environ.get("AK_SYSTEMD_FAILS")]:
    sys.exit(1)
if args == ["show", "-p", "MainPID", "--value", "lima-guestagent"]:
    print(7)
    sys.exit()
if args == ["daemon-reload"]:
    (proc / "loaded").write_text(dropin.read_text() if dropin.exists() else "")
if args == ["try-restart", "lima-guestagent"]:
    loaded = (proc / "loaded").read_text() if (proc / "loaded").exists() else ""
    (proc / "7/status").write_text({restricted!r} if "ProtectClock=yes" in loaded else {holds!r})
os.execv({spy!r}, [{spy!r}, *args])
'''


class LimaClock(test_slice.Installer):
    SECTION, NEXT = "# --- (g2c) the clock is NTP's alone", "# --- (h) a new phone key"  # (g3)'s tests run too

    def setUp(self):
        super().setUp()
        (self.bin / "sudo").write_text(SUDO.format(python=sys.executable))
        (self.bin / "sudo").chmod(0o755)
        spy = self.root / "spy/systemctl"
        spy.parent.mkdir()
        (self.bin / "systemctl").rename(spy)
        (self.bin / "systemctl").write_text(SYSTEMD.format(
            python=sys.executable, spy=str(spy), holds=HOLDS_CLOCK, restricted=RESTRICTED))
        (self.bin / "systemctl").chmod(0o755)
        self.proc = self.root / "proc"
        self.agent = self.proc / "7/status"
        self.agent.parent.mkdir(parents=True)
        self.agent.write_text(HOLDS_CLOCK)
        self.unit = self.root / "etc-systemd/lima-guestagent.service"
        self.dropin = self.unit.parent / "lima-guestagent.service.d/agentkit-clock.conf"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_SYSTEMD_SYSTEM": str(self.unit.parent), "AK_PROC": str(self.proc), "AK_UNIT_SUDO": "1"}))

    def lima(self):
        self.unit.parent.mkdir()
        self.unit.write_text("[Service]\n")

    def again(self, **env):
        """One more install: how often it restarted the guest agent, and the notes it left on the clock."""
        self.log.unlink(missing_ok=True)
        result = self.install(self.root, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.commands("systemctl").count(["systemctl", "try-restart", "lima-guestagent"]),
                [line for line in result.stderr.splitlines() if line.startswith("note: clock:")])

    def in_force(self):
        self.assertIn("[Service]\nProtectClock=yes\n", self.dropin.read_text())
        self.assertIn("ProtectClock=yes", (self.proc / "loaded").read_text())

    def test_a_machine_without_lima_is_left_alone(self):
        self.assertEqual(self.again(), (0, []))
        self.assertFalse(self.dropin.parent.exists())
        self.assertEqual(self.commands("sudo"), [])

    def test_a_lima_agent_holding_the_clock_restarts_once_under_the_drop_in(self):
        self.lima()
        self.assertEqual(self.again(), (1, []))
        self.in_force()
        self.assertEqual(self.agent.read_text(), RESTRICTED)
        self.assertEqual(self.again(), (0, []))

    def test_a_drop_in_deleted_or_changed_is_written_back_without_a_restart(self):
        self.lima()
        self.again()
        for change in (self.dropin.unlink, lambda: self.dropin.write_text("[Service]\nProtectClock=no\n")):
            change()
            self.assertEqual(self.again(), (0, []))
            self.in_force()

    def test_an_install_whose_reload_lookup_or_restart_failed_is_finished_by_the_next(self):
        self.lima()
        for step in ("daemon-reload", "show", "try-restart"):  # show: the agent's MainPID
            with self.subTest(step):
                self.agent.write_text(HOLDS_CLOCK)
                restarts, notes = self.again(AK_SYSTEMD_FAILS=step)
                self.assertEqual(len(notes), 1, notes)
                self.assertIn("re-run ./install.sh", notes[0])
                self.assertEqual(self.agent.read_text(), HOLDS_CLOCK)
                self.assertEqual(self.again(), (1, []))
                self.in_force()
                self.assertEqual(self.again(), (0, []))

    def test_without_passwordless_sudo_one_line_says_what_to_run(self):
        self.lima()
        restarts, notes = self.again(AK_UNIT_SUDO="0")
        self.assertEqual((restarts, len(notes)), (0, 1), notes)
        self.assertIn("sudo -v", notes[0])
        self.assertFalse(self.dropin.exists())


if __name__ == "__main__":
    unittest.main()

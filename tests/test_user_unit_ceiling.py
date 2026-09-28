"""The user unit's ceiling follows the machine too, where sudo needs no password.

Offline: the `Installer` fakes from `test_slice` -- a fake `systemctl`, `nproc` and
`tmux` on PATH, a throwaway HOME -- plus a fake `sudo` that answers the passwordless
probe and runs the commands it is given.  The system drop-in directory is redirected
under the temporary root, so no real unit file is read or written and systemd is never
reloaded.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_slice import Installer  # noqa: E402

# A sudo that only decides the passwordless probe itself: anything else it runs for
# real, so `mkdir` and `tee` write under the temporary root and `systemctl` is the spy
# from `test_slice`.  Nothing here can reach the account's own sudo timestamp.
SUDO = '''#!{python}
import json, os, pathlib, sys
with pathlib.Path(os.environ["AK_SLICE_LOG"]).open("a") as fh:
    fh.write(json.dumps(["sudo", *sys.argv[1:]]) + "\\n")
if sys.argv[1:] == ["-n", "true"]:
    sys.exit(0 if os.environ.get("AK_UNIT_SUDO") == "1" else 1)
args = [arg for arg in sys.argv[1:] if arg != "-n"]
os.execvp(args[0], args)
'''

HANDWRITTEN = """# a hand-written ceiling from before agentkit owned it
[Service]
TasksMax=4096
MemoryHigh=11G
MemoryMax=12500M
CPUQuota=700%
OOMPolicy=continue
"""


class UserUnitCeiling(Installer):
    SECTION = "# --- (g2b) the ceiling over the slice"
    NEXT = "# --- (h) a new phone key"   # the install runs (g2b) first, then (g3)

    def setUp(self):
        super().setUp()
        sudo = self.bin / "sudo"
        sudo.write_text(SUDO.format(python=sys.executable))
        sudo.chmod(0o755)
        self.systemd = self.root / "etc-systemd"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_SYSTEMD_SYSTEM": str(self.systemd), "AK_UNIT_SUDO": "1"}))

    def unit_limits(self):
        return self.systemd / f"user@{os.getuid()}.service.d/agentkit-limits.conf"

    def unit_lines(self, result):
        return [line for line in result.stdout.splitlines() if "user-unit:" in line]

    def test_a_with_sudo_more_cores_get_a_larger_ceiling(self):
        home = self.root / "sudo-home"
        home.mkdir()
        result = self.install(home, AK_SLICE_CPUS="8")
        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.unit_limits().read_text()
        self.assertTrue(written.startswith("# Written by agentkit's install.sh"),
                        written)
        # tasks are a share of the kernel's thread limit, not a per-core count: on a
        # small machine a per-core count would shrink the slice below what (g3) gives it
        self.assertIn("[Service]\nTasksMax=4%\n", written)
        self.assertIn("MemoryHigh=80%\nMemoryMax=90%\n", written)
        self.assertIn("CPUQuota=700%\n", written)
        self.assertIn("OOMPolicy=continue\n", written)
        self.assertIn(["systemctl", "daemon-reload"], self.commands("systemctl"))
        # every sudo write stayed under the temporary root
        for argv in self.commands("sudo"):
            if "mkdir" in argv or "tee" in argv:
                self.assertTrue(any(str(self.root) in arg for arg in argv), argv)
        # a larger machine raises the same ceiling through the slice's own quota
        again = self.install(home, AK_SLICE_CPUS="16")
        self.assertEqual(again.returncode, 0, again.stderr)
        rewritten = self.unit_limits().read_text()
        self.assertIn("TasksMax=4%\n", rewritten)
        self.assertIn("CPUQuota=1500%\n", rewritten)
        self.assertIn("OOMPolicy=continue\n", rewritten)
        # and the unit is written before the slice derives from it
        source = (REPO / "install.sh").read_text()
        self.assertLess(source.index("agentkit-limits.conf"),
                        source.index("user_tasks=$(systemctl show"))

    def test_b_without_sudo_one_line_and_no_write(self):
        home = self.root / "no-sudo-home"
        home.mkdir()
        result = self.install(home, AK_SLICE_CPUS="8", AK_UNIT_SUDO="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.unit_lines(result)
        self.assertEqual(len(lines), 1, result.stdout)
        self.assertIn("sudo -v", lines[0])
        self.assertIn("install.sh", lines[0])
        self.assertFalse(self.systemd.exists())
        self.assertEqual(self.commands("sudo"), [["sudo", "-n", "true"]])

    def test_c_the_handwritten_file_is_taken_over(self):
        home = self.root / "takeover-home"
        home.mkdir()
        unit = self.unit_limits()
        unit.parent.mkdir(parents=True)
        unit.write_text(HANDWRITTEN)
        result = self.install(home, AK_SLICE_CPUS="8")
        self.assertEqual(result.returncode, 0, result.stderr)
        rewritten = unit.read_text()
        self.assertTrue(rewritten.startswith("# Written by agentkit's install.sh"),
                        rewritten)
        self.assertIn("TasksMax=4%\n", rewritten)
        self.assertIn("MemoryHigh=80%\nMemoryMax=90%\n", rewritten)
        self.assertIn("OOMPolicy=continue\n", rewritten)

    def test_d_another_dropin_is_left_alone(self):
        home = self.root / "other-dropin-home"
        home.mkdir()
        other = self.unit_limits().parent / "99-owner.conf"
        other.parent.mkdir(parents=True)
        owned = "[Service]\nCPUQuota=50%\n# the owner's own hand\n"
        other.write_text(owned)
        result = self.install(home, AK_SLICE_CPUS="8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(other.read_text(), owned)
        self.assertTrue(self.unit_limits().read_text().startswith(
            "# Written by agentkit's install.sh"))
        # and an agentkit-limits.conf of the owner's own is left byte-identical
        self.unit_limits().write_text("[Service]\nTasksMax=12\n")
        owned_result = self.install(home, AK_SLICE_CPUS="16")
        self.assertEqual(owned_result.returncode, 0, owned_result.stderr)
        self.assertEqual(self.unit_limits().read_text(), "[Service]\nTasksMax=12\n")
        self.assertIn("left byte-identical", owned_result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

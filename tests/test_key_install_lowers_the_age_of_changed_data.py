"""A server install calls sysctl_set for each changed-data value above its ceiling.

Offline: install.sh's changed-data step, after the core dump step that defines sysctl_set and
here finds no core pattern to read, as on a Mac, against fake live values and an empty sysctl.d
under a temporary root, with test_install_compressed_swap's fake `sudo`, which answers the
passwordless probe and runs what it is given there.  The real kernel is never read or written.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_install_compressed_swap import SUDO

REPO = Path(__file__).resolve().parents[1]
AGE, INTERVAL = "vm.dirty_expire_centisecs", "vm.dirty_writeback_centisecs"
OURS = "# Written by agentkit's install.sh"


class ChangedDataAge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vm = self.root / "proc/sys/vm"
        self.vm.mkdir(parents=True)
        self.sysctl_d = self.root / "etc/sysctl.d"
        self.sysctl_d.mkdir(parents=True)
        self.log = self.root / "sudo.log"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        sudo = self.bin / "sudo"
        sudo.write_text(SUDO.format(python=sys.executable))
        sudo.chmod(0o755)

    def set_live(self, age, interval):
        for key, value in ((AGE, age), (INTERVAL, interval)):
            (self.vm / key.split(".")[1]).write_text(f"{value}\n")

    def live(self):
        return [(self.vm / key.split(".")[1]).read_text().strip() for key in (AGE, INTERVAL)]

    def install(self, sudo_ok="1", sandbox="0", role="server"):
        source = (REPO / "install.sh").read_text()
        body = (source[source.index("# --- a crashed program leaves no core dump file"):
                       source.index("# --- (g2a)")]
                + source[source.index("# --- the kernel writes changed data out sooner"):
                         source.index("# --- every session has room for its inotify")])
        prelude = (f'set -euo pipefail\nSANDBOX={sandbox}\nROLE={role}\n'
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "note: $*" >&2; }\n')
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "AK_CORE_PATTERN": str(self.root / "proc/sys/kernel/core_pattern"),
               "AK_PROC_SYS_VM": str(self.vm), "AK_SYSCTL_D": str(self.sysctl_d),
               "AK_SUDO_LOG": str(self.log), "AK_SUDO_OK": sudo_ok}
        result = subprocess.run(["bash", "-c", prelude + body], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def entries(self, key):
        return [path.name for path in self.sysctl_d.iterdir()
                if path.read_text().startswith(OURS) and f"{key} = " in path.read_text()]

    def sudo_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_a_a_server_at_3000_and_500_ends_at_1000_and_200(self):
        self.set_live(3000, 500)
        result = self.install()
        self.assertEqual(self.live(), ["1000", "200"])
        self.assertEqual(len(self.entries(AGE)), 1)
        self.assertEqual(len(self.entries(INTERVAL)), 1)
        self.assertEqual(len(list(self.sysctl_d.iterdir())), 2)
        # the screen says each change in plain words: the value, what it was and is, and why
        self.assertIn(f"{AGE} lowered from 3000 to 1000: changed data is old", result.stdout)
        self.assertIn(f"{INTERVAL} lowered from 500 to 200: the kernel looks", result.stdout)
        # every write went under the temporary root
        for argv in self.sudo_calls():
            if {"tee", "mkdir", "rm"} & set(argv):
                self.assertTrue(argv[-1].startswith(str(self.root)), argv)

    def test_b_a_server_at_or_below_both_ceilings_keeps_its_own(self):
        for age, interval in ((500, 100), (1000, 200)):
            self.set_live(age, interval)
            self.install()
            self.assertEqual(self.live(), [str(age), str(interval)])
            self.assertEqual(list(self.sysctl_d.iterdir()), [])
            self.assertEqual(self.sudo_calls(), [])

    def test_c_a_server_at_3000_and_100_gets_the_age_alone(self):
        self.set_live(3000, 100)
        self.install()
        self.assertEqual(self.live(), ["1000", "100"])
        self.assertEqual(len(self.entries(AGE)), 1)
        self.assertEqual(self.entries(INTERVAL), [])
        self.assertEqual(len(list(self.sysctl_d.iterdir())), 1)

    def test_d_no_passwordless_sudo_keeps_both_and_one_note_names_them(self):
        self.set_live(3000, 500)
        result = self.install(sudo_ok="0")
        self.assertEqual(self.live(), ["3000", "500"])
        self.assertEqual(list(self.sysctl_d.iterdir()), [])
        [note] = [line for line in result.stderr.splitlines() if line.startswith("note:")]
        self.assertIn(f"{AGE} stays 3000", note)
        self.assertIn(f"{INTERVAL} stays 500", note)
        self.assertIn("sudo -v", note)
        self.assertEqual({tuple(argv) for argv in self.sudo_calls()}, {("-n", "true")})

    def test_e_a_client_a_sandbox_or_a_host_with_no_numbers_sets_nothing(self):
        self.install()
        self.set_live("", "")
        self.install()
        self.set_live(3000, 500)
        self.install(role="client")
        self.install(sandbox="1")
        self.assertEqual(self.live(), ["3000", "500"])
        self.assertEqual(list(self.sysctl_d.iterdir()), [])
        self.assertEqual(self.sudo_calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""install.sh sets the host to write no core dump files, now and on every boot.

Offline: install.sh's core dump step alone, against a fake core_pattern and sysctl.d under
a temporary root, with test_install_compressed_swap's fake `sudo`, which answers the
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
COLLECTOR = "|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h"


class NoCoreDumps(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.pattern = self.root / "proc/sys/kernel/core_pattern"
        self.pattern.parent.mkdir(parents=True)
        self.sysctl_d = self.root / "etc/sysctl.d"
        self.sysctl_d.mkdir(parents=True)
        (self.sysctl_d / "10-magic-sysrq.conf").write_text("kernel.sysrq = 176\n")
        self.log = self.root / "sudo.log"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        sudo = self.bin / "sudo"
        sudo.write_text(SUDO.format(python=sys.executable))
        sudo.chmod(0o755)

    def install(self, sudo_ok="1", sandbox="0"):
        source = (REPO / "install.sh").read_text()
        body = source[source.index("# --- a crashed program leaves no core dump file"):
                      source.index("# --- (g2a)")]
        prelude = (f'set -euo pipefail\nSANDBOX={sandbox}\n'
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "note: $*" >&2; }\n')
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "AK_CORE_PATTERN": str(self.pattern), "AK_SYSCTL_D": str(self.sysctl_d),
               "AK_SUDO_LOG": str(self.log), "AK_SUDO_OK": sudo_ok}
        result = subprocess.run(["bash", "-c", prelude + body], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def live(self):
        return self.pattern.read_text().strip()

    def entries(self):
        return {path.name: path.read_text() for path in self.sysctl_d.iterdir()}

    def boot(self):
        """The pattern systemd-sysctl leaves: every entry in name order, the last one's."""
        pattern = "core"
        for _, text in sorted(self.entries().items()):
            for line in text.splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "kernel.core_pattern":
                    pattern = value.strip()
        return pattern

    def sudo_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def discards_dumps_now_and_on_every_boot(self):
        self.pattern.write_text("core\n")
        before = self.entries()
        self.install()
        self.assertEqual(self.live(), "|/bin/false")
        [ours] = set(self.entries()) - set(before)
        self.assertEqual(ours, max(self.entries()))
        self.assertGreater(ours, "99-sysctl.conf")
        self.assertEqual(self.boot(), self.live())
        # every write went under the temporary root
        for argv in self.sudo_calls():
            if "tee" in argv or "mkdir" in argv:
                self.assertTrue(argv[-1].startswith(str(self.root)), argv)
        # a second install changes neither, and asks sudo for nothing
        after = self.entries()
        self.log.unlink()
        self.install()
        self.assertEqual(self.live(), "|/bin/false")
        self.assertEqual(self.entries(), after)
        self.assertEqual(self.sudo_calls(), [])

    def test_a_the_default_pattern_discards_dumps_now_and_on_every_boot(self):
        self.discards_dumps_now_and_on_every_boot()

    def test_b_so_it_does_under_a_sysctl_conf_that_sets_the_default(self):
        (self.root / "etc/sysctl.conf").write_text("kernel.core_pattern=core\n")
        (self.sysctl_d / "99-sysctl.conf").symlink_to("../sysctl.conf")
        self.discards_dumps_now_and_on_every_boot()

    def test_c_a_pattern_piped_to_a_program_is_left_alone(self):
        self.pattern.write_text(COLLECTOR + "\n")
        before = self.entries()
        self.install()
        self.assertEqual(self.live(), COLLECTOR)
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [])

    def test_d_no_passwordless_sudo_writes_nothing_and_names_the_setting(self):
        self.pattern.write_text("core\n")
        before = self.entries()
        result = self.install(sudo_ok="0")
        self.assertIn("kernel.core_pattern", result.stderr)
        self.assertIn("sudo -v", result.stderr)
        self.assertEqual(self.live(), "core")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [["-n", "true"]])

    def test_e_a_sandbox_install_touches_nothing(self):
        self.pattern.write_text("core\n")
        before = self.entries()
        self.install(sandbox="1")
        self.assertEqual(self.live(), "core")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

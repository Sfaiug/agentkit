"""install.sh leaves every session room for its inotify instances, now and on every boot.

Offline: install.sh's inotify step, after the core dump step that holds the boot entry rule and
here finds no core pattern to read, as on a Mac, against a fake limit and sysctl.d under a
temporary root, with test_install_compressed_swap's fake `sudo`, which answers the passwordless
probe and runs what it is given there.  The real kernel is never read or written.
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
KEY = "fs.inotify.max_user_instances"
OURS = "# Written by agentkit's install.sh"


class RoomForInotify(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.limit = self.root / "proc/sys/fs/inotify/max_user_instances"
        self.limit.parent.mkdir(parents=True)
        self.sysctl_d = self.root / "etc/sysctl.d"
        self.sysctl_d.mkdir(parents=True)
        (self.sysctl_d / "10-magic-sysrq.conf").write_text("kernel.sysrq = 176\n")
        (self.root / "etc/sysctl.conf").write_text(f"{KEY}=128\n")
        (self.sysctl_d / "99-sysctl.conf").symlink_to("../sysctl.conf")
        # an earlier install's core dump entry, which sorts after every entry but ak's
        (self.sysctl_d / "zz-agentkit-no-core-dumps.conf").write_text(
            f"{OURS}: a crashed program leaves no core dump file\n"
            "kernel.core_pattern = |/bin/false\n")
        self.log = self.root / "sudo.log"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        sudo = self.bin / "sudo"
        sudo.write_text(SUDO.format(python=sys.executable))
        sudo.chmod(0o755)

    def install(self, sudo_ok="1", sandbox="0"):
        source = (REPO / "install.sh").read_text()
        body = (source[source.index("# --- a crashed program leaves no core dump file"):
                       source.index("# --- (g2a)")]
                + source[source.index("# --- every session has room for its inotify"):
                         source.index("# --- (i)")])
        prelude = (f'set -euo pipefail\nSANDBOX={sandbox}\n'
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "note: $*" >&2; }\n')
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "AK_CORE_PATTERN": str(self.root / "proc/sys/kernel/core_pattern"),
               "AK_INOTIFY_INSTANCES": str(self.limit), "AK_SYSCTL_D": str(self.sysctl_d),
               "AK_SUDO_LOG": str(self.log), "AK_SUDO_OK": sudo_ok}
        result = subprocess.run(["bash", "-c", prelude + body], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def live(self):
        return self.limit.read_text().strip()

    def entries(self):
        return {path.name: path.read_text() for path in self.sysctl_d.glob("*.conf")}

    def others(self):
        return {name: text for name, text in self.entries().items() if not text.startswith(OURS)}

    def ours(self):
        return [name for name, text in self.entries().items()
                if text.startswith(OURS) and KEY in text]

    def boot(self):
        """The limit systemd-sysctl leaves: every entry in name order, the last one's."""
        limit = "128"
        for _, text in sorted(self.entries().items()):
            for line in text.splitlines():
                key, _, value = line.partition("=")
                if key.strip() == KEY:
                    limit = value.strip()
        return limit

    def sudo_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def leaves_room_now_and_on_every_boot(self):
        others = self.others()
        core = self.entries()["zz-agentkit-no-core-dumps.conf"]
        result = self.install()
        self.assertIn("inotify:", result.stdout)
        self.assertEqual(self.live(), "8192")
        # one entry of ak's, named for what it sets, after every entry that is not ak's
        [ours] = self.ours()
        self.assertIn("inotify", ours)
        self.assertNotIn("core", ours)
        self.assertGreater(ours, max(others))
        self.assertEqual(self.others(), others)
        self.assertEqual(self.entries()["zz-agentkit-no-core-dumps.conf"], core)
        self.assertEqual(self.boot(), "8192")
        # every write went under the temporary root
        for argv in self.sudo_calls():
            if {"tee", "mkdir", "rm"} & set(argv):
                self.assertTrue(argv[-1].startswith(str(self.root)), argv)
        # a second install changes neither, and asks sudo for nothing
        after = self.entries()
        self.log.unlink()
        self.install()
        self.assertEqual(self.live(), "8192")
        self.assertEqual(self.entries(), after)
        self.assertEqual(self.sudo_calls(), [])

    def test_a_a_host_at_128_has_room_for_8192_now_and_on_every_boot(self):
        self.limit.write_text("128\n")
        self.leaves_room_now_and_on_every_boot()

    def test_b_an_entry_sorting_after_ours_moves_ours_after_it(self):
        self.limit.write_text("128\n")
        self.leaves_room_now_and_on_every_boot()
        (self.sysctl_d / "zzz-local.conf").write_text(f"{KEY} = 128\n")
        # the next boot applies it after ours, and the next install finds its limit
        self.limit.write_text(self.boot() + "\n")
        self.leaves_room_now_and_on_every_boot()

    def test_c_a_host_that_allows_more_keeps_its_own(self):
        self.limit.write_text("65536\n")
        before = self.entries()
        self.install()
        self.assertEqual(self.live(), "65536")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [])

    def test_d_no_passwordless_sudo_writes_nothing_and_names_the_setting(self):
        self.limit.write_text("128\n")
        before = self.entries()
        result = self.install(sudo_ok="0")
        self.assertIn(KEY, result.stderr)
        self.assertIn("sudo -v", result.stderr)
        self.assertEqual(self.live(), "128")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [["-n", "true"]])

    def test_e_a_sandbox_install_or_a_host_with_no_limit_touches_nothing(self):
        before = self.entries()
        self.install()
        self.limit.write_text("128\n")
        self.install(sandbox="1")
        self.assertEqual(self.live(), "128")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.sudo_calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

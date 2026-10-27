"""install.sh turns zswap on where swap is on a disk, now and on every boot.

Offline: install.sh's (g2a) step alone, against a fake /sys, /proc/swaps and tmpfiles.d
under a temporary root, with a fake `sudo` on PATH that answers the passwordless probe
and runs what it is given there.  The real kernel is never read or written.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SUDO = '''#!{python}
import json, os, pathlib, sys
with pathlib.Path(os.environ["AK_SUDO_LOG"]).open("a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["-n", "true"]:
    sys.exit(0 if os.environ.get("AK_SUDO_OK") == "1" else 1)
args = [arg for arg in sys.argv[1:] if arg != "-n"]
os.execvp(args[0], args)
'''

DISK = "Filename\tType\tSize\tUsed\tPriority\n/swapfile file\t4194300\t0\t-2\n"
ZRAM = "Filename\tType\tSize\tUsed\tPriority\n/dev/zram0 partition\t4194300\t0\t100\n"


class CompressedSwap(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.params = self.root / "sys/module/zswap/parameters"
        self.params.mkdir(parents=True)
        for name, value in {"enabled": "N", "compressor": "lzo", "zpool": "zbud",
                            "shrinker_enabled": "N", "max_pool_percent": "20"}.items():
            (self.params / name).write_text(value + "\n")
        self.tmpfiles = self.root / "etc/tmpfiles.d"
        self.swaps = self.root / "swaps"
        self.log = self.root / "sudo.log"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        sudo = self.bin / "sudo"
        sudo.write_text(SUDO.format(python=sys.executable))
        sudo.chmod(0o755)

    def install(self, swaps, sudo_ok="1"):
        self.swaps.write_text(swaps)
        source = (REPO / "install.sh").read_text()
        body = source[source.index("# --- (g2a)"):source.index("# --- (g2b)")]
        prelude = ('set -euo pipefail\nSANDBOX=0\n'
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "note: $*" >&2; }\n')
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "AK_SYS": str(self.root / "sys"), "AK_PROC_SWAPS": str(self.swaps),
               "AK_TMPFILES_D": str(self.tmpfiles), "AK_SUDO_LOG": str(self.log),
               "AK_SUDO_OK": sudo_ok}
        result = subprocess.run(["bash", "-c", prelude + body], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def param(self, name):
        return (self.params / name).read_text().strip()

    def sudo_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_a_disk_swap_gets_zswap_now_and_on_boot(self):
        self.install(DISK)
        self.assertEqual(self.param("enabled"), "Y")
        self.assertEqual(self.param("compressor"), "zstd")
        self.assertEqual(self.param("zpool"), "zsmalloc")
        self.assertEqual(self.param("shrinker_enabled"), "Y")
        self.assertEqual(self.param("max_pool_percent"), "20")   # the kernel's own share
        entry = (self.tmpfiles / "agentkit-zswap.conf").read_text()
        for line in ("w /sys/module/zswap/parameters/compressor - - - - zstd",
                     "w /sys/module/zswap/parameters/zpool - - - - zsmalloc",
                     "w /sys/module/zswap/parameters/shrinker_enabled - - - - Y",
                     "w /sys/module/zswap/parameters/enabled - - - - Y"):
            self.assertIn(line + "\n", entry)
        self.assertNotIn("max_pool_percent", entry)
        # every write went under the temporary root
        for argv in self.sudo_calls():
            if "tee" in argv or "mkdir" in argv:
                self.assertTrue(argv[-1].startswith(str(self.root)), argv)
        # a second install finds it on and asks sudo for nothing
        self.log.unlink()
        self.install(DISK)
        self.assertEqual(self.sudo_calls(), [])

    def test_b_no_swap_and_zram_are_left_alone(self):
        for swaps in ("Filename\tType\tSize\tUsed\tPriority\n", ZRAM):
            self.install(swaps)
            self.assertEqual(self.param("enabled"), "N")
            self.assertFalse(self.tmpfiles.exists())
            self.assertEqual(self.sudo_calls(), [])

    def test_c_a_sudo_asking_for_a_password_is_noted_and_skipped(self):
        result = self.install(DISK, sudo_ok="0")
        self.assertIn("zswap", result.stderr)
        self.assertIn("sudo -v", result.stderr)
        self.assertEqual(self.param("enabled"), "N")
        self.assertFalse(self.tmpfiles.exists())
        self.assertEqual(self.sudo_calls(), [["-n", "true"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)

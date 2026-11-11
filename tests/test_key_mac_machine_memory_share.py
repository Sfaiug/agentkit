"""On a Mac, an install holds ak's existing Linux machine to its share of the Mac's memory.

Memory is a reservation the Mac never gets back once the machine has touched it, so a machine
that Lima reports with more than its share, as one made by hand may be, is held to it through
Lima's own `limactl start --memory=<share>`: Lima writes the size into the machine's file,
starts a stopped machine with it, and leaves a running one running, to take it from its next
start.  The install says so in one line naming both sizes.  A machine with its share or less gets
no such call and no line, and cores, which come back to macOS whenever the machine idles, are
left as they are.  Black-box on the Mac of fakes of tests/test_key_install_mac_linux_machine.py,
a Mac mini of 10 cores and 64 GiB, whose machine was made by hand with all 10 cores; its
`limactl` records each call and reports the machine's memory from `<root>/memory`.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from test_key_install_mac_linux_machine import Mac


class MadeByHand(Mac):
    def __init__(self, memory, status):
        super().__init__(cpus=10, memory_gib=64)
        root = self.home.root
        self.yaml = self.home.path / ".lima/ak/lima.yaml"
        self.yaml.parent.mkdir(parents=True)
        self.yaml.write_text(f"cpus: 10\nmemory: {memory}GiB\n")
        (self.yaml.parent / "ssh.config").write_text("Host lima-ak\n")
        shutil.copy(root / "limactl", self.home.bin / "limactl")
        (root / "memory").write_text(str(memory))
        (root / "machine").write_text(status)
        out = self.install().out
        for path, name in ((root, "<root>"), (installer.CHECKOUT, "<checkout>")):
            out = out.replace(str(path), name)
        self.sizes = [line for line in out.splitlines() if "GiB" in line]
        self.calls = [call for call in self.lima() if call[0] != "list"]

    def sized(self, flag):
        return [call for call in self.calls if any(arg.startswith(flag) for arg in call)]


class Held(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.macs = {}
        for memory, status in ((56, "Running"), (56, "Stopped"), (48, "Running"),
                               (32, "Running")):
            cls.macs[memory, status] = mac = MadeByHand(memory, status)
            cls.addClassCleanup(mac.close)

    def test_a_running_machine_with_more_takes_its_share_from_its_next_start(self):
        mac = self.macs[56, "Running"]
        [start] = [call for call in mac.calls if call[0] == "start"]
        self.assertIn("--memory=48", start)
        self.assertNotIn("stop", [call[0] for call in mac.calls])
        self.assertEqual((mac.home.root / "machine").read_text(), "Running")
        [line] = mac.sizes
        for words in ("56 GiB", "48 GiB", "next start"):
            self.assertIn(words, line)
        self.assertEqual(mac.yaml.read_text(), "cpus: 10\nmemory: 56GiB\n")

    def test_a_stopped_one_starts_with_its_share(self):
        mac = self.macs[56, "Stopped"]
        [start] = [call for call in mac.calls if call[0] == "start"]
        self.assertIn("--memory=48", start)
        self.assertEqual((mac.home.root / "machine").read_text(), "Running")
        [line] = mac.sizes
        for words in ("56 GiB", "48 GiB"):
            self.assertIn(words, line)

    def test_one_with_its_share_or_less_is_left_as_it_is(self):
        for memory in (48, 32):
            with self.subTest(memory=memory):
                mac = self.macs[memory, "Running"]
                self.assertEqual(mac.sized("--memory"), [])
                self.assertEqual(mac.sizes, [])

    def test_its_cores_are_left_as_they_are(self):
        for mac in self.macs.values():
            self.assertEqual(mac.sized("--cpus"), [])


if __name__ == "__main__":
    unittest.main()

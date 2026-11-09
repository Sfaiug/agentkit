"""A machine is added on `c` by its ssh address, asked once as the tick asks each machine.

Owner, 29 Oct and 3 Nov 2026: add another machine on the settings screen, and ak tells what it
is.  Black-box: AK_BIN runs under a terminal in a temporary HOME.  ssh is a fake: an address in
ANSWERING runs the command it is given, the real probe, on a Mac's tools; any other is refused
as ssh refuses a key, with a warning before it.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ANSWERING = ("acme-box", "acme@acme-mini.example")
SSH = """#!/bin/sh
while :; do case $1 in --) shift; break ;; -[bcDEeFIiJLlmOoPpQRSWw]) shift 2 ;; -*) shift ;;
  *) break ;; esac; done
echo "$1" >>{asked}
if grep -qxF -e "$1" {answering}; then shift; PATH={tools}:$PATH exec sh -c "$*"; fi
echo "Warning: Permanently added '$1' (ED25519) to the list of known hosts." >&2
echo "$1: Permission denied (publickey)." >&2
exit 255
"""
# 10 cores, 16 GB with 20% free, a load of 2.41, on power with no battery
MAC = {"uname": "case $1 in -s) echo Darwin ;; -m) echo arm64 ;; esac",
       "sysctl": "case $2 in hw.ncpu) echo 10 ;; hw.memsize) echo 17179869184 ;;"
                 " vm.loadavg) echo '{ 2.41 2.10 1.90 }' ;; esac",
       "memory_pressure": "echo 'System-wide memory free percentage: 20%'",
       "pmset": "echo \"Now drawing from 'AC Power'\"",
       "df": "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
             "echo '/dev/disk3s5 971350180 700000000 220200960 77% /System/Volumes/Data'"}
SIZE = "new · 10 cores · 16 GB · 24% busy · 13 of 16 GB used · tests"
ADD = "+ add a machine"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMachineIsAdded(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        self.config = akconfig.write(home, ["fable"])
        self.asked, tools = home.root / "asked", home.root / "mac"
        tools.mkdir()
        for name, body in MAC.items():
            (tools / name).write_text(f"#!/bin/sh\n{body}\n")
            (tools / name).chmod(0o755)
        (home.root / "answering").write_text("\n".join(ANSWERING) + "\n")
        home.fake("ssh", SSH.format(asked=shlex.quote(str(self.asked)), tools=shlex.quote(str(tools)),
                                    answering=shlex.quote(str(home.root / "answering"))))
        self.term = Terminal(home, "attach", "--overlay", size=(120, 40), env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 6))       # one model, then the sixth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen and ADD in screen)
        self.term.keys("Down", "Down")        # past this one and Google Cloud
        self.term.wait(f"› {ADD}")

    def add(self, address, shown):
        """The screen once `address`, typed into the last row's field, has come to `shown`."""
        self.term.keys("Enter")
        self.term.wait("its ssh address")
        self.term.type(address)
        self.term.keys("Enter")
        return self.term.wait(lambda screen: shown in " ".join(screen.split()))

    def ssh_asked(self):
        """Each address ssh was given, oldest first."""
        return self.asked.read_text().split() if self.asked.exists() else []

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_one_that_answers_is_written_and_listed_new_and_then_refused(self):
        self.add("acme-box", f"acme-box {SIZE}")
        self.assertIn("[machines.acme-box]\n", self.config.read_text())
        self.assertEqual(akconfig.read(self.home)["machines"], {"acme-box": {}})
        record = json.loads((self.home.path / ".agentkit/state/machines.json").read_text())
        self.assertEqual(record["acme-box"]["said"]["cores"], 10)
        written = self.config.read_bytes()
        self.add("acme-box", "acme-box is a machine already")
        self.assertEqual(self.config.read_bytes(), written)
        self.assertEqual(self.ssh_asked(), ["acme-box"])
        self.leave()

    def test_one_that_does_not_answer_writes_nothing_and_says_why_under_the_row(self):
        before = self.config.read_bytes()
        address = "acme@acme-box.example"
        screen = self.add(address, f"{address} did not answer: {address}: Permission denied "
                                   "(publickey).")
        lines = screen.splitlines()
        row = next(number for number, line in enumerate(lines) if ADD in line)
        said = next(number for number, line in enumerate(lines) if "Permission denied" in line)
        self.assertLess(row, said)
        self.assertNotIn("Permanently added", screen)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.home.path / ".agentkit/state/machines.json").exists())
        self.assertEqual(self.ssh_asked(), [address])
        self.leave()

    def test_one_toml_cannot_hold_bare_is_written_quoted_and_reads_back_the_same(self):
        self.add("acme@acme-mini.example", f"acme@acme-mini.example {SIZE}")
        self.assertIn('[machines."acme@acme-mini.example"]\n', self.config.read_text())
        self.assertEqual(akconfig.read(self.home)["machines"], {"acme@acme-mini.example": {}})
        self.leave()


if __name__ == "__main__":
    unittest.main()

"""Enter on `+ add a machine`'s empty field finds the machine that ran the line, on Tailscale.

Owner, 29 Oct 2026: "The config screen's Machines page shows one line to paste on the new
machine.  It installs ak, joins your Tailscale network and reports in."  Enter with nothing typed
asks, once, each of the home's Tailscale peers that could be the new machine, by ak's key alone,
and one that answers as `ak@<its Tailscale name>` is listed and written to config.toml as a typed
address is.  Black-box: AK_BIN under a terminal in a temporary HOME; tailscale a fake printing
the test's status; ssh one writing down its words, asked what an address is (-G) reading the
test's config as the real ssh does, else answering as the probe does for an address let in and
refused for any other.
"""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

REAL_SSH = shutil.which("ssh", path="/usr/bin:/bin")
SSH = """#!{python}
import json, os, sys
words = sys.argv[1:]
with open({asked!r}, "a") as asked:
    asked.write(json.dumps(words) + "\\n")
if "-G" in words:
    os.execv({ssh!r}, [{ssh!r}, "-F", {config!r}, *words])
address = words[words.index("--") + 1]
if address not in open({answering!r}).read().split():
    sys.exit(address + ": Permission denied (publickey).")
print({readings!r})
"""
# what the probe says on a Linux machine of 8 cores and 16 GB, half of it free, at a load of 2
READINGS = ("system Linux\nprocessor x86_64\ncores 8\nmemory_mb 16384\nfree_mb 8192\nload 2.00\n"
            "disk_free_mb 102400\nbattery 0\npower 1")
SIZE = "● runs ● tests new · 8 cores · 16 GB · 25% busy · 8 of 16 GB used"
NET = "tail-acme.ts.net"
NEW = ("acme-box", True, "linux", 1)        # (name, online, OS, Tailscale user) of a peer
REFUSING = ("acme-old", True, "linux", 1)
# each would answer: offline, a Mac, a friend's, and one config.toml names by an ssh alias
NEVER = (("acme-off", False, "linux", 1), ("acme-mac", True, "macOS", 1),
         ("acme-pal", True, "linux", 2), ("acme-known", True, "linux", 1))
# The owner's ssh config: the alias config.toml names, and the owner's own key for every host.
CONFIG = f"Host acme-known\n  HostName acme-known.{NET}\nHost *\n  IdentityFile {{own}}\n"
LINE = re.compile(r"^ *curl -fsSL \S+ \| sudo bash -s -- '([^']+)' tailscale$", re.M)
ADD = "+ add a machine"
WORDS = ("Run this on a new Linux machine, then press Enter for ak to find it on your Tailscale "
         "network, or type above the address it prints:")
NONE = "no machine on your Tailscale network answered ak's key"
NOTHING = "no Tailscale network here to look through"


def address(peer):
    return f"ak@{peer[0]}.{NET}"


def status(*peers, state="Running"):
    """`tailscale status --json` on a home of Tailscale user 1, with `peers`."""
    return json.dumps({"BackendState": state, "Self": {"DNSName": f"acme-home.{NET}.", "UserID": 1},
                       "Peer": {f"nodekey:{name}": {"DNSName": f"{name}.{NET}.", "Online": online,
                                                    "OS": system, "UserID": user}
                                for name, online, system, user in peers}})


def without(home, name):
    """The Home's PATH, its fakes first, with no `name` on it: its other programs linked."""
    (linked := home.root / "path").mkdir()
    for folder in map(Path, home.env["PATH"].split(os.pathsep)[1:]):
        for program in folder.iterdir() if folder.is_dir() else ():
            if program.name != name and not os.path.lexists(linked / program.name):
                (linked / program.name).symlink_to(program)
    (home.bin / name).unlink()
    return os.pathsep.join([str(home.bin), str(linked)])


@unittest.skipUnless(REAL_TMUX and REAL_SSH and shutil.which("ssh-keygen"),
                     "no tmux, ssh or ssh-keygen here")
class AMachineThatRanTheLineIsAddedByItself(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        self.config = akconfig.write(home, ["fable"], extra="\n[machines.acme-known]\n")
        self.asked, self.answering, self.status, self.ssh_config = map(
            home.root.joinpath, ("asked", "answering", "status", "ssh_config"))
        self.ssh_config.write_text(CONFIG.format(own=home.path / ".ssh/acme-own"))
        self.answering.write_text("")
        home.fake("ssh", SSH.format(python=sys.executable, ssh=REAL_SSH, readings=READINGS,
                                    config=str(self.ssh_config), asked=str(self.asked),
                                    answering=str(self.answering)))
        home.fake("tailscale", f"#!/bin/sh\nexec cat {shlex.quote(str(self.status))}\n")

    def let_in(self, *peers):
        """Those ssh answers, as a machine that ran the line lets ak's key in."""
        self.answering.write_text("".join(f"{address(peer)}\n" for peer in peers))

    def open(self, env=None):
        """The screen once `+ add a machine`'s field is open, past three rows."""
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1", **(env or {})})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen and ADD in screen)
        self.term.keys("Down", "Down")        # past this one and acme-known
        self.term.wait(f"› {ADD}")
        self.term.keys("Enter")
        self.term.wait(lambda screen: LINE.search(self.term.screen(copied=True)))
        return self.term.screen(copied=True)

    def enter(self, shown):
        """Enter on the field with nothing typed, until the page says `shown`."""
        self.term.keys("Enter")
        self.term.wait(lambda screen: shown in " ".join(screen.split()) and "curl" not in screen)

    def calls(self):
        """The words of each ssh, oldest first."""
        lines = self.asked.read_text().splitlines() if self.asked.exists() else []
        return [*map(json.loads, lines)]

    def probes(self):
        """The words of each ssh asking a machine, not what an address is (-G)."""
        return [words for words in self.calls() if "-G" not in words]

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_a_peer_that_answers_ak_s_key_is_listed_and_written_by_its_tailscale_name(self):
        self.status.write_text(status(NEW))
        self.let_in(NEW)                        # the line run on it
        key = LINE.search(self.open())[1]
        self.enter(f"{address(NEW)} {SIZE}")
        self.assertEqual(akconfig.read(self.home)["machines"], {"acme-known": {}, address(NEW): {}})
        self.assertIn(f'[machines."{address(NEW)}"]\n', self.config.read_text())
        [words] = self.probes()
        # as the real ssh reads them, the owner's config named first: by ak's key alone
        got = subprocess.run([REAL_SSH, "-G", "-F", self.ssh_config,
                              *words[:words.index("--") + 2]],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        [only] = [line.split(" ", 1)[1] for line in got if line.startswith("identityfile ")]
        public = subprocess.run(["ssh-keygen", "-y", "-f", only], capture_output=True,
                                text=True, check=True).stdout
        self.assertEqual(public.split()[:2], key.split()[:2])
        self.assertLessEqual({"identitiesonly yes", "stricthostkeychecking accept-new"}, {*got})
        self.leave()

    def test_only_a_peer_that_could_be_it_is_asked_and_one_refusing_saves_nothing(self):
        self.status.write_text(status(REFUSING, *NEVER))
        self.let_in(*NEVER)
        before = self.config.read_bytes()
        self.open()
        self.assertEqual(self.calls(), [])      # nothing before Enter
        self.enter(NONE)
        self.assertEqual([words[words.index("--") + 1] for words in self.probes()],
                         [address(REFUSING)])
        self.assertEqual(self.config.read_bytes(), before)
        self.leave()

    def test_with_no_tailscale_network_enter_runs_no_ssh_and_says_why(self):
        before = self.config.read_bytes()
        self.status.write_text(status(NEW, state="NeedsLogin"))     # one logged out
        self.let_in(NEW)
        for gone in (False, True):                  # then no tailscale at all
            env = {"PATH": without(self.home, "tailscale")} if gone else None
            self.assertIn(WORDS, " ".join(self.open(env).split()))
            self.enter(NOTHING)
            self.assertEqual(self.calls(), [])
            self.assertEqual(self.config.read_bytes(), before)
            self.leave()


if __name__ == "__main__":
    unittest.main()

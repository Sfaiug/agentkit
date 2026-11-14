"""`+ add a machine` shows the line to paste on a new machine, and ak reaches one that ran it.

Owner, 29 Oct 2026: "The config screen's Machines page shows one line to paste on the new
machine."  With its field open, `+ add a machine` shows tools/join.sh's line, fetched from this
checkout's origin on its default branch, with the public half of a key pair ak makes the first
time and keeps in its secrets.  Copied off the screen as a terminal copies it, at 80 columns as at
200, it is one command, and pasted into bash it fetches that URL whatever a fork's branch is
named.  Every ssh to a machine config.toml names, the one asking a typed address and the tick's
check alike, offers the keys SSH's own config gives the address, in its order, then that key, as
the real ssh reads its words, and the first learns a host key it has not seen.
Black-box: AK_BIN runs under a terminal in a temporary HOME; ssh is a fake that reads a config
as the real ssh does, the test's (`CONFIG`), and else writes down each call's words and is
refused as ssh is refused a key; git, where a fork's branch is asked for, a fake naming it.
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
from fixtures.akbin import REAL_TMUX, SYSTEM, Home, boxable
from fixtures.akterm import Terminal

REPO = Path(__file__).resolve().parents[1]
REAL_SSH = shutil.which("ssh", path="/usr/bin:/bin")
SSH = """#!{python}
import json, os, sys
if "-G" in sys.argv:
    os.execv({ssh!r}, [{ssh!r}, "-F", {config!r}, *sys.argv[1:]])
with open({asked!r}, "a") as asked:
    asked.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stderr.write("Permission denied (publickey).\\n")
sys.exit(255)
"""
ADD = "+ add a machine"
LINE = re.compile(r"^ *(curl -fsSL (\S+) \| sudo bash -s -- '([^']+)' tailscale)$", re.M)
TYPED = "ak@acme-new.example"
# A machine set up by hand names its own key, alone.
CONFIG = "Host acme-box\n  IdentityFile {key}\n  IdentitiesOnly yes\n"
# git, but origin's default branch is a fork's, named as git allows and a shell would cut short
FORK = ('#!/bin/sh\ncase " $* " in *" symbolic-ref "*" refs/remotes/origin/HEAD "*)\n'
        '  echo {branch}; exit;; esac\nexec {git} "$@"\n')
# what a pasted line runs: curl writing down its words, sudo nothing
PASTED = {"curl": "#!/bin/sh\nprintf '%s\\n' \"$@\" >{asked}\n", "sudo": "#!/bin/sh\n"}


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                          text=True).stdout.strip()


def raw(branch):
    """The URL of tools/join.sh on `branch` of this checkout's origin."""
    owner_name = "/".join(git("remote", "get-url", "origin").rstrip("/").removesuffix(".git")
                          .replace(":", "/").split("/")[-2:]).lower()
    return f"https://raw.githubusercontent.com/{owner_name}/{branch}/tools/join.sh"


def keygen(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", path], check=True)


def settings(config, *words):
    """{setting: its values} the real ssh reads, given `words` and `config`."""
    shown = subprocess.run([REAL_SSH, "-G", "-F", config, *words], capture_output=True,
                           text=True, check=True).stdout
    read = {}
    for line in shown.splitlines():
        read.setdefault(line.partition(" ")[0], []).append(line.partition(" ")[2])
    return read


@unittest.skipUnless(REAL_TMUX and shutil.which("ssh-keygen"), "no tmux or ssh-keygen here")
class AddAMachineShowsTheLine(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, ["fable"], extra="\n[machines.acme-box]\n")
        self.ssh_log, self.config = home.path / "asked", home.path / "ssh_config"
        self.own_key = home.path / "acme-key"
        keygen(self.own_key)
        self.config.write_text(CONFIG.format(key=self.own_key))
        home.fake("ssh", SSH.format(python=sys.executable, ssh=REAL_SSH, config=str(self.config),
                                    asked=str(self.ssh_log)))
        self.term = Terminal(home, "attach", "--overlay", size=(80, 40), env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 6))       # one model, then the sixth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen and ADD in screen)
        self.term.keys("Down", "Down", "Down")  # past this one, acme-box and Google Cloud
        self.term.wait(f"› {ADD}")

    def opened(self):
        """The line the open field shows as copied off the screen, its URL and its key."""
        self.term.keys("Enter")
        self.term.wait(lambda screen: LINE.search(self.term.screen(copied=True)))
        return LINE.search(self.term.screen(copied=True)).groups()

    def private_half(self, key):
        """The file of the Home's secrets whose public half is `key`."""
        halves = [path for path in (self.home.path / ".agentkit/secrets").iterdir()
                  if path.is_file() and subprocess.run(
                      ["ssh-keygen", "-y", "-f", path], stdin=subprocess.DEVNULL,
                      capture_output=True, text=True).stdout.split()[:2] == key.split()[:2]]
        self.assertEqual(len(halves), 1, key)
        return halves[0]

    def asked(self, address):
        """What the real ssh reads, by the test's config, of each ssh ak gave `address`."""
        calls = [words for words in map(json.loads, self.ssh_log.read_text().splitlines())
                 if address in words]
        self.assertTrue(calls, address)
        return [settings(self.config, *words[:words.index(address) + 1]) for words in calls]

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_the_open_field_shows_the_line_with_origin_and_a_key_ak_keeps(self):
        _, url, key = self.opened()
        branch = git("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
        self.assertEqual(url, raw(branch.removeprefix("origin/") or "HEAD"))
        self.assertIn("the address it prints", " ".join(self.term.screen().split()))
        self.assertRegex(key, r"^ssh-ed25519 \S+")
        self.assertEqual(self.private_half(key).stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE KEY", self.term.screen())
        self.term.keys("Escape")
        self.term.wait(lambda screen: "curl" not in screen)
        self.assertEqual(self.opened()[2], key)
        self.leave()

    def test_copied_at_80_columns_as_at_200_the_line_is_one_command(self):
        line = self.opened()[0]
        self.assertNotIn(line, self.term.screen())    # the terminal wraps it at 80 columns
        self.assertEqual(subprocess.run(["bash", "-n", "-c", line]).returncode, 0, line)
        self.term.resize(200, 40)
        self.term.wait(lambda screen: line in screen)
        self.assertEqual(LINE.search(self.term.screen(copied=True))[1], line)
        self.leave()

    def test_pasted_into_bash_the_line_fetches_a_forks_branch_whatever_it_is_named(self):
        branch = "release;next"
        self.home.fake("git", FORK.format(branch=shlex.quote(f"origin/{branch}"), git=shlex.quote(
            shutil.which("git", path=os.pathsep.join(SYSTEM)))))
        line, pasted = self.opened()[0], self.home.root / "pasted"
        pasted.mkdir()
        asked = pasted / "asked"
        for name, script in PASTED.items():
            (pasted / name).write_text(script.format(asked=shlex.quote(str(asked))))
            (pasted / name).chmod(0o755)
        done = subprocess.run([shutil.which("bash"), "-c", line], env={"PATH": str(pasted)},
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(asked.read_text().splitlines(), ["-fsSL", raw(branch)],
                         line + "\n" + done.stderr)
        self.leave()

    @unittest.skipUnless(REAL_SSH and boxable(), "no ssh, or no bwrap boxing a tick")
    def test_the_ssh_asking_a_typed_address_and_the_ticks_check_offer_the_key(self):
        key = str(self.private_half(self.opened()[2]))
        self.term.type(TYPED)
        self.term.keys("Enter")
        self.term.wait(lambda screen: f"{TYPED} did not answer" in " ".join(screen.split()))
        own = settings(self.config, TYPED)["identityfile"]
        for read in self.asked(TYPED):  # ssh's defaults, each as ssh would offer it, then ak's
            self.assertEqual(read["identityfile"], [*own, key])
            self.assertEqual(read["stricthostkeychecking"], ["accept-new"])
        self.leave()
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        for read in self.asked("acme-box"):     # its own key first, so it answers as before
            self.assertEqual(read["identityfile"], [str(self.own_key), key])
            self.assertEqual(read["identitiesonly"], ["yes"])


if __name__ == "__main__":
    unittest.main()

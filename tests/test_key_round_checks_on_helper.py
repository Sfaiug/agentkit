"""A round's done-when commands run on the suite helper first, as one piece, when it has room.

All green there is the round's answer and nothing runs here.  Anything else runs the same
commands here, and here decides; a helper with no room sends them here at once; a list naming
`AK_SHARD` keeps today's way, its other commands here.  Black-box: the program `AK_BIN` names runs
a task from outside through tests/fixtures/akbin.py, with scripted harnesses from fakeadapter.py.
The helper is a fake `ssh` that runs each piece here, under a HOME of its own, on the tree its
parcel carries.  A command marks where it ran in the Git storage of the checkout it runs in.
"""

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

READINGS = json.dumps({"cpus": 4, "load": 0, "free_mb": 16000})
ROOM, FULL = "cpus 2\nload 0\nroom_mb 65536", "cpus 2\nload 2\nroom_mb 65536"
MARK = 'echo {} >>"$(git rev-parse --git-common-dir)/marks"'
# Only this host's HOME holds ak's config.
HERE_ONLY = 'test -f "$HOME/.agentkit/config.toml"'

# The words after the alias are one `bash -c <mac.sh> mac.sh <verb> ...` line.
SSH = """#!{python}
import os, shlex, subprocess, sys, tarfile
helper = {helper!r}
words = shlex.split(sys.argv[-1])
verb, args = words[words.index("mac.sh") + 1], words[words.index("mac.sh") + 2:]
with open(helper + "/calls", "a") as calls:
    calls.write(verb + "\\n")
if verb == "probe":
    print(open(helper + "/probe").read())
elif verb == "prepare":    # KEY IMAGE REPO, the parcel on stdin
    tarfile.open(fileobj=sys.stdin.buffer, mode="r|").extractall(helper + "/" + args[0])
elif verb == "run":        # KEY IMAGE NAME CPUS MEMORY_MB REPO SHARD BRANCH DEFAULT PROGRAMS COMMAND
    there = helper + "/" + args[0]
    work = there + "/work-" + args[2]
    subprocess.run(["git", "clone", "-q", "--no-checkout", there + "/repo.bundle", work], check=True)
    tree = open(there + "/heads").read().split()[0]
    subprocess.run(["git", "-C", work, "checkout", "-q", tree], check=True)
    os.makedirs(helper + "/home", exist_ok=True)
    sys.exit(subprocess.run(["bash", "-c", args[-1]], cwd=work, env={{
        **os.environ, "HOME": helper + "/home", "AK_SHARD": args[6]}}).returncode)
"""


class Round:
    probe = ROOM
    done_when = ()

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        akconfig.write(cls.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        cls.helper = cls.home.root / "helper"
        cls.helper.mkdir()
        (cls.helper / "probe").write_text(cls.probe)
        cls.home.fake("ssh", SSH.format(python=sys.executable, helper=str(cls.helper)))
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, done_when=cls.done_when)
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300,
                               env={"AK_HOST_READINGS": READINGS})
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.log = [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line)
                   for line in (cls.run_dir / "log.txt").read_text().splitlines()]
        cls.checks = (cls.run_dir / "round-1" / "donewhen.log").read_text()

    def marks(self):
        """(the marks commands left here, those they left on the helper)."""
        here = self.rig.path / ".git" / "marks"
        there = [line for path in sorted(self.helper.glob("*/work-*/.git/marks"))
                 for line in path.read_text().split()]
        return (here.read_text().split() if here.exists() else []), there

    def calls(self):
        path = self.helper / "calls"
        return path.read_text().split() if path.exists() else []

    def passed(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.state.get("verdict"), "PASS", self.state)


class AllGreenThere(Round, unittest.TestCase):
    # The second reads what the first left untracked: one piece, one tree.
    done_when = ("echo made >made.txt", MARK.format('"$(cat made.txt)"'))

    def test_nothing_runs_here_and_the_round_passes(self):
        self.passed()
        self.assertEqual(self.marks(), ([], ["made"]))
        self.assertEqual(self.calls(), ["probe", "known", "prepare", "run", "finish"])
        self.assertIn("done-when on the suite helper acme-mac, as one piece", self.log)

    def test_the_reviewer_reads_what_ran_and_where(self):
        self.assertIn("On the suite helper acme-mac, as one piece: [exit 0]\n"
                      f"--- $ {self.done_when[0]} ---\n--- $ {self.done_when[1]} ---", self.checks)
        for cmd in self.done_when:
            self.assertIn(f"\n\n$ {cmd}\n[exit 0]", self.checks)


class RedThere(Round, unittest.TestCase):
    done_when = (MARK.format("mark"), HERE_ONLY)

    def test_the_commands_run_here_which_decides(self):
        self.passed()
        self.assertEqual(self.marks(), (["mark"], ["mark"]))
        self.assertEqual(self.calls()[-2:], ["run", "finish"])
        self.assertIn("done-when runs here: helper acme-mac failed (exit 1)", self.log)

    def test_what_the_piece_printed_there_stays_above_the_run_here(self):
        there = self.checks.index("On the suite helper acme-mac, as one piece: [exit 1]\n")
        self.assertLess(there, self.checks.index(f"$ {HERE_ONLY}\n[exit 0]"))


class NoRoomThere(Round, unittest.TestCase):
    probe = FULL
    done_when = (MARK.format("mark"),)

    def test_the_commands_run_here_at_once(self):
        self.passed()
        self.assertEqual(self.marks(), (["mark"], []))
        self.assertNotIn("run", self.calls())
        self.assertIn("done-when runs here: helper acme-mac has no room "
                      "(0 spare CPUs and 65536 MiB)", self.log)


class NamingTheShard(Round, unittest.TestCase):
    done_when = (MARK.format("mark"), ': "$AK_SHARD"; true')

    def test_no_piece_of_the_list_goes_and_its_other_commands_run_here(self):
        self.passed()
        self.assertEqual(self.marks(), (["mark"], []))
        self.assertFalse([line for line in self.log if line.startswith("done-when runs here")])
        self.assertNotIn("On the suite helper", self.checks)


if __name__ == "__main__":
    unittest.main()

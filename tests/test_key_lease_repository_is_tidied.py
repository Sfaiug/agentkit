"""A read of ak's lease asks git for its housekeeping in the lease's repository,
`.agentkit/tmp/lease/repo`: where the user's git config sets `gc.auto` to 1 and `gc.autoDetach` to
false, a home's turn, or a standby's pass, leaves none of the loose object files there older than
git's two weeks, and the turn swaps the lease and the pass keeps its record of it as they do
without it.  A `git` that exits 1 for `gc` changes neither the turn's swap nor its exit.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, a home
and, for the watch, a standby that is its client, whose installs share one origin, each machine's
clock from AK_NOW, a later command at a later clock, and each case builds its own.  git estimates
how many objects are loose from one of its folders of them, so the key puts two no ref names in
each before it sets every loose object file there fifteen days back: those objects and times are
its own input.  What came back is each command's exit and output, the refs git reads in the origin
and in the lease's repository, which of the files the key aged are there, and the fake git's log.
"""

import hashlib
import itertools
import os
import shlex
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.akinstall import _git
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import REF, kept, lease, made, refs
from test_key_home_holds_a_lease import named, now
from test_key_standby_watches_its_homes_lease import SEEN, now as watch_now

GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))


def aged(machine):
    """Every loose object file of `machine`'s lease's repository, set fifteen days back, once two
    objects no ref names are put in each of git's folders of them: more than gc.auto's 1 by
    whichever folder git counts."""
    repo = kept(machine)
    form = _git(repo, "rev-parse", "--show-object-format")
    folders = {f"{n:02x}": [] for n in range(256)}
    for data in (b"%d" % n for n in itertools.count()):
        if all(len(held) == 2 for held in folders.values()):
            break
        held = folders[hashlib.new(form, b"blob %d\0%s" % (len(data), data)).hexdigest()[:2]]
        if len(held) < 2:
            held.append(data)
    with tempfile.TemporaryDirectory() as scratch:
        paths = []
        for data in itertools.chain(*folders.values()):
            paths.append(Path(scratch, data.decode()))
            paths[-1].write_bytes(data)
        _git(repo, "hash-object", "-w", *map(str, paths))
    files = list((repo / "objects").glob("??/*"))
    back = time.time() - 15 * 24 * 3600
    for path in files:
        os.utime(path, (back, back))
    return files


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TheLeasesRepositoryIsTidied(unittest.TestCase):
    def machines(self, *names, **kwargs):
        machines = Machines(*names, **kwargs)
        self.addCleanup(machines.close)
        for machine in machines:
            with (machine.path / ".gitconfig").open("a") as config:
                config.write("[gc]\n\tauto = 1\n\tautoDetach = false\n")
        return machines

    def turn(self, home, turn):
        """`home`'s `turn`th `ak lease`, which prints nothing and exits 0."""
        self.assertEqual(lease(home, now=now(turn)), (0, "", ""))

    def swaps(self, home, turn):
        """`home`'s `turn`th turn, which leaves on the origin a lease other than the one it found,
        the value of the ref named for its stamp."""
        before = home.install.refs().get(REF)
        self.turn(home, turn)
        after = home.install.refs().get(REF)
        self.assertNotIn(None, (before, after))
        self.assertNotEqual(after, before)
        self.assertEqual(made(home).get(named(turn)), after)

    def assertGone(self, files):
        self.assertEqual(sum(map(Path.exists, files)), 0, "files aged past two weeks are left")

    def test_a_homes_turn_leaves_no_file_aged_past_two_weeks_and_swaps(self):
        mini, = self.machines("acme-mini")
        self.turn(mini, 0)
        self.swaps(mini, 1)
        self.swaps(mini, 2)
        files = aged(mini)
        self.swaps(mini, 3)
        self.assertGone(files)
        self.swaps(mini, 4)

    def test_a_standbys_pass_meeting_a_new_value_leaves_no_file_aged_past_two_weeks(self):
        home, standby = self.machines("acme-mini", "acme-vm",
                                      now={"acme-mini": now(0), "acme-vm": watch_now(0)})
        standby.client_of(home)

        def passes(minute):
            done = standby.ak("standby", "acme-mini", env={"AK_NOW": watch_now(minute)})
            self.assertEqual(done.code, 0, done.err)

        self.turn(home, 0)
        passes(1)
        files = aged(standby)
        self.swaps(home, 1)
        passes(2)
        self.assertGone(files)
        repo = kept(standby)
        seen = refs(repo).get(SEEN)
        self.assertIsNotNone(seen, "the pass kept no record")
        message = _git(repo, "cat-file", "commit", seen).partition("\n\n")[2]
        self.assertEqual(message.split(" ")[0], home.install.refs()[REF])

    def test_a_git_failing_its_housekeeping_leaves_the_turn_as_it_is(self):
        mini, = self.machines("acme-mini")
        log = mini.log("gc")
        asked = shlex.quote(str(mini.at / log.relative_to(mini.root)))
        mini.fake("git", f'#!/bin/sh\ncase "$1" in gc) echo >>{asked}; exit 1;; esac\n'
                         f'exec {shlex.quote(GIT)} "$@"\n')
        self.turn(mini, 0)
        self.swaps(mini, 1)
        self.assertTrue(log.exists(), "no turn asked git for its housekeeping")


if __name__ == "__main__":
    unittest.main()

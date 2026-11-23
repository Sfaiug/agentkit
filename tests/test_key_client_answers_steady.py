"""`ak standby --steady` prints nothing and exits 0 on a machine steady enough to be given home: its
record of a server names a home, it keeps no value of the lease it made, a ref under `refs/made/`
named for a stamp, which a git that will not list them leaves unsaid, it has been up half an hour,
its last pass from that home that ended well left a stamp of this boot under 10 minutes old by both
clocks, and its watch holds a record of the lease made on this boot; else it exits 1.  Given a
second word, help's too, it is refused as `ak standby`'s other misuse is, printing nothing.

Black-box, through tests/fixtures/akbin.py, its clock from AK_NOW, set where its Home is built: 40
minutes into boot `acme-boot-1` on both clocks unless a case says otherwise.  The key writes the
record of a server and the stamp of a pass, a stamp's line then the alias, and makes the lease's
repository with git: `refs/seen` at a commit whose message is a value and a stamp's line, and
where a case keeps a value, a ref under `refs/made/` named for a stamp.
"""

import os
import shlex
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, Home
from fixtures.akinstall import _git
from test_key_ak_lease_creates_a_lease import LEASE
from test_key_standby_watches_its_homes_lease import SEEN

SERVER = ".agentkit/state/server"     # the record of a server, naming the home
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well
REPO = LEASE / "repo"   # the lease's repository, where the watch keeps its record
EMPTY = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"     # git's empty tree, which every repo has
VALUE = "5" * 40    # the lease's value the watch read
UP = 40     # minutes the machine has been up
GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))     # git itself, as no shim on PATH is


def at(minutes, since=None, boot="acme-boot-1"):
    """A stamp's line `minutes` into `boot` by the wall clock and `since`, `minutes` unless named,
    by the clock since boot: each clock a float, so the line reads back as written."""
    return f"{1789000000.5 + 60 * minutes} {60.0 * (minutes if since is None else since)} {boot}"


def steady(home):
    """`home` made acme-vm's client and steady, UP minutes into its boot: its record of a server,
    its lease's repository, and `up`'s."""
    home.write(SERVER, "acme-vm\n")
    repo = home.path / REPO
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "--bare")
    up(home, UP)


def up(home, minutes):
    """`home` `minutes` into its boot, its pass's stamp 5 minutes old and its watch's record 15."""
    home.env["AK_NOW"] = at(minutes)
    copied(home, at(minutes - 5))
    seen(home, at(minutes - 15))


def copied(home, line, alias="acme-vm"):
    home.write(STAMP, f"{line}\n{alias}\n")


def seen(home, line):
    repo = home.path / REPO
    commit = _git(repo, "commit-tree", EMPTY, "-m", f"{VALUE} {line}")
    _git(repo, "update-ref", SEEN, commit)


class AClientAnswersSteady(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        steady(self.home)
        self.repo = self.home.path / REPO

    def answer(self, *words):
        """The exit of `ak standby --steady` with `words`, which printed nothing."""
        done = self.home.ak("standby", "--steady", *words)
        self.assertEqual(done.out, "", done)
        return done.code

    def test_a_client_up_half_an_hour_with_a_young_copy_and_the_lease_seen_is_steady(self):
        self.assertEqual(self.answer(), 0)

    def test_one_without_a_record_of_a_server_is_not(self):
        (self.home.path / SERVER).unlink()
        self.assertEqual(self.answer(), 1)

    def test_one_up_29_minutes_is_not(self):
        up(self.home, 29)
        self.assertEqual(self.answer(), 1)

    def test_one_whose_copy_is_10_minutes_old_by_one_clock_is_not(self):
        copied(self.home, at(UP - 10, since=UP - 5))
        self.assertEqual(self.answer(), 1)

    def test_one_whose_copy_is_of_another_boot_is_not(self):
        copied(self.home, at(UP - 5, boot="acme-boot-0"))
        self.assertEqual(self.answer(), 1)

    def test_one_whose_copy_is_of_another_home_is_not(self):
        copied(self.home, at(UP - 5), alias="acme-old")
        self.assertEqual(self.answer(), 1)

    def test_one_without_a_copy_is_not(self):
        (self.home.path / STAMP).unlink()
        self.assertEqual(self.answer(), 1)

    def test_one_keeping_a_value_it_made_is_not(self):
        made = "refs/made/" + at(UP - 3).replace(" ", "_")
        _git(self.repo, "update-ref", made, _git(self.repo, "rev-parse", SEEN))
        self.assertEqual(self.answer(), 1)

    def test_a_ref_under_refs_made_named_for_no_stamp_is_no_value_kept(self):
        _git(self.repo, "update-ref", "refs/made/acme", _git(self.repo, "rev-parse", SEEN))
        self.assertEqual(self.answer(), 0)

    def test_one_keeping_a_value_its_git_will_not_list_is_not(self):
        made = "refs/made/" + at(UP - 3).replace(" ", "_")
        _git(self.repo, "update-ref", made, _git(self.repo, "rev-parse", SEEN))
        # a git refusing whatever names refs/made/, which says nothing of what is kept there
        self.home.fake("git", f'#!/bin/sh\ncase "$*" in *refs/made*) exit 74;; esac\n'
                              f'exec {shlex.quote(GIT)} "$@"\n')
        self.assertEqual(self.answer(), 1)

    def test_one_whose_watch_holds_no_record_is_not(self):
        _git(self.repo, "update-ref", "-d", SEEN)
        self.assertEqual(self.answer(), 1)

    def test_one_whose_watch_holds_a_record_of_another_boot_is_not(self):
        seen(self.home, at(UP - 15, boot="acme-boot-0"))
        self.assertEqual(self.answer(), 1)

    def test_one_without_a_lease_repository_is_not(self):
        shutil.rmtree(self.repo)
        self.assertEqual(self.answer(), 1)

    def test_a_second_word_is_refused_as_any_other_misuse(self):
        misuse = self.home.ak("standby", "--began", "extra")
        self.assertNotEqual(misuse.code, 0, misuse.out + misuse.err)
        # help too, whose 0 would read as the answer
        for word in ("extra", "-h", "--help"):
            with self.subTest(word=word):
                self.assertEqual(self.answer(word), misuse.code)


if __name__ == "__main__":
    unittest.main()

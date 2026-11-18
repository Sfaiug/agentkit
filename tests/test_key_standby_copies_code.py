"""`ak standby ALIAS` copies ~/code, a project's `.git` folder and what git ignores too; the next
pass brings what changed and takes what the home removed.  A file beside ~/code does not come,
and a home without ~/code leaves the copy's as it was.  Some of ~/code stays as it is here, in a
pass that ends well and copies the rest.  What the home's account cannot read, ~/code itself
too, however many such files there are.  A link to a folder outside ~/code, ~/code itself as one
on either machine.  A repository whose git data is not all in ~/code, or holds what the pass
leaves out: one with it in ~/code crosses, git reading it here.  A lock in a repository's git
data.  And each name in ~/code on the way from this machine's `ak` command to the ak it runs.
Black-box (fixtures/twohomes.py)."""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

MAIN, GIT, IGNORED = "code/acme-api/main.py", "code/acme-api/.git/HEAD", "code/acme-api/.venv/cfg"
OTHER, BESIDE = "code/acme-web/index.html", "notes/plan.txt"
STORE = "store/acme-api"    # on the home, a repository outside ~/code
# on the home, each project that keeps git data outside ~/code, by how it is made of STORE
OUTSIDE = {"code/acme-link": None,          # a link to it
           "code/group/acme-api": None,     # in a folder that is a link to the one it is in
           "code/acme-split": ("clone", "-q", "--separate-git-dir=store/acme-split.git", STORE),
           "code/acme-tree": ("-C", STORE, "worktree", "add", "-q", "--detach"),
           "code/acme-borrow": ("clone", "-q", "--shared", STORE),
           "code/acme-objects": ("clone", "-q", STORE)}     # its objects moved out, a link left
# and each that keeps it in ~/code: a clone, a checkout of it, a clone borrowing its objects, and
# one whose git data is beside it
INSIDE = {"code/acme-café": ("clone", "-q", STORE),
          "code/acme-café-tree": ("-C", "code/acme-café", "worktree", "add", "-q", "--detach"),
          "code/acme-café-borrow": ("clone", "-q", "--shared", "code/acme-café"),
          "code/acme-beside": ("clone", "-q", "--separate-git-dir=code/acme-beside.git", STORE)}


def code(machine):
    return {at: data for at, data in machine.tree().items() if at.startswith("code/")}


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesTheProjects(unittest.TestCase):
    def standby(self, here, home):
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def git(self, machine, *args):
        done = machine.run("git", *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def repository(self, machine, path, text):
        machine.write(f"{path}/main.py", text)
        self.git(machine, "init", "-q", path)
        self.git(machine, "-C", path, "add", "main.py")
        self.git(machine, "-C", path, "commit", "-qm", "start")

    def test_a_pass_copies_code_whole_then_what_changed_and_what_the_home_removed(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            for path in (MAIN, GIT, IGNORED, OTHER, BESIDE):
                home.write(path, f"the home's {path}")
            for change in (lambda: None,
                           lambda: (home.write(MAIN, "changed"), (home.path / IGNORED).unlink(),
                                    shutil.rmtree(home.path / "code/acme-web"))):
                change()
                done = here.ak("standby", home.name)
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(code(here), code(home))
            self.assertNotIn(BESIDE, here.tree())
            shutil.rmtree(home.path / "code")
            done = here.ak("standby", home.name)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertIn(GIT, code(here))

    @unittest.skipIf(os.geteuid() == 0, "root reads a file whatever its mode")
    def test_what_the_home_cannot_read_in_code_is_left_out_and_the_rest_of_the_pass_crosses(self):
        machines = home, here = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.addCleanup((home.path / "code").chmod, 0o700)      # for its close to remove it
        here.client_of(home)
        state, left = ".agentkit/state/watch.json", "code/acme-api/build/left"
        kept = "code/acme-web"
        self.repository(home, kept, "first")
        # one file, then as many as no command would take as words, then ~/code itself
        for step, lock in enumerate((lambda: (home.path / left).chmod(0),
                                     lambda: [(home.path / "code/acme-api/build"
                                               / f"{number:05}-{'x' * 130}").touch(mode=0)
                                              for number in range(16000)],
                                     lambda: (home.path / "code").chmod(0))):
            for path in (MAIN, left, state):
                home.write(path, f"before {step}")
            self.standby(here, home)
            for path in (MAIN, state):
                home.write(path, f"after {step}, longer")
            lock()
            self.standby(here, home)
            self.assertEqual({path: (here.path / path).read_text() for path in (MAIN, left, state)},
                             {MAIN: f"before {step}" if step == 2 else f"after {step}, longer",
                              left: f"before {step}", state: f"after {step}, longer"})
            (home.path / "code").chmod(0o700)
            (home.path / left).chmod(0o600)
        # a repository holding one crosses whole, or not at all
        self.standby(here, home)
        self.git(home, "-C", kept, "commit", "-qm", "second", "--allow-empty")
        home.write(f"{kept}/.git/left", "")
        (home.path / kept / ".git/left").chmod(0)
        self.standby(here, home)
        self.assertEqual(self.git(here, "-C", kept, "log", "--format=%s"), "start\n")
        (home.path / kept / ".git/left").chmod(0o600)
        self.standby(here, home)
        self.assertEqual(self.git(here, "-C", kept, "log", "--format=%s"), "second\nstart\n")

    def test_a_lock_in_a_repositorys_git_data_stays_where_it_is(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            self.repository(home, "code/acme-api", "the home's")
            self.git(home, "clone", "-q", "--separate-git-dir=code/acme-web.git", "code/acme-api",
                     "code/acme-web")
            self.standby(here, home)
            ours, tracked = "code/acme-api/.git/index.lock", "code/acme-api/Cargo.lock"
            for path in ("code/acme-api/.git/refs/heads/main.lock", "code/acme-web.git/HEAD.lock",
                         tracked):
                home.write(path, "the home's")
            here.write(ours, "this machine's")
            self.standby(here, home)
            self.assertEqual({path for path in code(here) if path.endswith(".lock")},
                             {ours, tracked})

    def test_a_repository_with_git_data_outside_code_stays_as_the_copy_has_it(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            self.repository(home, STORE, "the home's")
            self.repository(home, "store/group/acme-api", "the home's")
            (home.path / "code").mkdir()
            (home.path / "code/acme-link").symlink_to(f"../{STORE}")
            (home.path / "code/group").symlink_to("../store/group")
            for path, made in ((path, made) for kind in (OUTSIDE, INSIDE)
                               for path, made in kind.items() if made):
                self.git(home, *made, f"{home.env['HOME']}/{path}")
            objects = home.path / "code/acme-objects/.git/objects"
            objects.rename(home.path / "store/objects")
            objects.symlink_to(f"{home.env['HOME']}/store/objects")
            for path in OUTSIDE:
                self.repository(here, path, "the copy's")
            def read(machine, paths):
                return {path: self.git(machine, "-C", path, "show", "HEAD:main.py")
                        for path in paths}
            self.assertEqual(read(home, (*OUTSIDE, *INSIDE)),
                             dict.fromkeys((*OUTSIDE, *INSIDE), "the home's"))
            self.standby(here, home)
            self.assertEqual(read(here, (*OUTSIDE, *INSIDE)),
                             {**dict.fromkeys(OUTSIDE, "the copy's"),
                              **dict.fromkeys(INSIDE, "the home's")})
            # ~/code itself a repository with its git data outside, then a link
            held = code(here)
            for change in (lambda: self.git(home, "init", "-q", "--separate-git-dir=store/code.git",
                                            "code"),
                           lambda: ((home.path / "code").rename(home.path / "disk"),
                                    (home.path / "code").symlink_to("disk"))):
                change()
                home.write(MAIN, "made since")
                self.standby(here, home)
                self.assertFalse((here.path / "code").is_symlink())
                self.assertEqual(code(here), held)

    def test_each_name_in_code_on_the_way_to_the_ak_this_machine_runs_stays(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            for machine in (home, here):
                machine.write(MAIN, f"{machine.name}'s")
            # ~/agentkit a link to a link in ~/code to the install, in a folder there whose name
            # rsync would read as a pattern, and where the home has a file
            (here.path / "code/tools[vm]").mkdir()
            (here.path / "agentkit").rename(here.path / "code/tools[vm]/agentkit")
            (here.path / "code/acme-ak").symlink_to("tools[vm]/agentkit")
            (here.path / "agentkit").symlink_to("code/acme-ak")
            home.write("code/tools[vm]", "the home's")
            self.standby(here, home)
            self.assertEqual((here.path / MAIN).read_text(), "acme-mini's")
            self.assertEqual(here.run(".local/bin/ak", "standby", "--help").code, 0)

    def test_code_that_is_a_link_here_stays_one(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            home.write(MAIN, "the home's")
            here.write("disk/acme-api/main.py", "this machine's")
            (here.path / "code").symlink_to("disk")
            self.standby(here, home)
            self.assertTrue((here.path / "code").is_symlink())
            self.assertEqual((here.path / MAIN).read_text(), "this machine's")


if __name__ == "__main__":
    unittest.main()

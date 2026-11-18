"""`ak standby ALIAS` copies ~/code, a project's `.git` folder and what git ignores too; the next
pass brings what changed and takes what the home removed.  A file beside ~/code does not come,
and a home without ~/code leaves the copy's as it was.  Four things in ~/code stay as they are
here, in a pass that ends well: what the home's account cannot read, the rest of the pass
crossing; a lock in a `.git` folder; a folder, or link to one, whose `.git` names git data outside
~/code, and ~/code itself where the home's is a link; and the ak this machine runs.  A repository
with its git data in ~/code crosses, git reading it here.  Black-box (fixtures/twohomes.py)."""

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
# on the home, each project that keeps git data outside ~/code, by how it was made
OUTSIDE = {"code/acme-link": None,      # a link to the repository
           "code/acme-split": ("clone", "-q", "--separate-git-dir=store/acme-split.git", STORE),
           "code/acme-tree": ("-C", STORE, "worktree", "add", "-q", "--detach"),
           "code/acme-borrow": ("clone", "-q", "--shared", STORE)}
# and each that keeps it in ~/code: a clone, a checkout of it, and a clone borrowing its objects
INSIDE = {"code/acme-web": ("clone", "-q", STORE),
          "code/acme-web-tree": ("-C", "code/acme-web", "worktree", "add", "-q", "--detach"),
          "code/acme-web-borrow": ("clone", "-q", "--shared", "code/acme-web")}


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
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            state, left = ".agentkit/state/watch.json", "code/acme-api/.git/objects/left"
            for path in (MAIN, left, state):
                home.write(path, "first")
            self.standby(here, home)
            for path in (MAIN, left, state):
                home.write(path, "second, longer")
            (home.path / left).chmod(0)
            self.standby(here, home)
            self.assertEqual({path: (here.path / path).read_text() for path in (MAIN, left, state)},
                             {MAIN: "second, longer", left: "first", state: "second, longer"})

    def test_a_lock_in_a_git_folder_stays_where_it_is(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            theirs, ours = "code/acme-api/.git/refs/heads/main.lock", "code/acme-api/.git/index.lock"
            tracked = "code/acme-api/Cargo.lock"
            for path in (GIT, theirs, tracked):
                home.write(path, f"the home's {path}")
            here.write(ours, "this machine's")
            self.standby(here, home)
            self.assertEqual({path for path in code(here) if path.endswith(".lock")}, {ours, tracked})
            self.assertIn(GIT, code(here))

    def test_git_data_outside_code_leaves_its_project_as_the_copy_has_it(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            self.repository(home, STORE, "the home's")
            (home.path / "code").mkdir()
            (home.path / "code/acme-link").symlink_to(f"../{STORE}")
            for path, made in ((path, made) for kind in (OUTSIDE, INSIDE)
                               for path, made in kind.items() if made):
                self.git(home, *made, f"{home.env['HOME']}/{path}")
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
            held = code(here)
            (home.path / "code").rename(home.path / "disk")
            (home.path / "code").symlink_to("disk")
            self.standby(here, home)
            self.assertFalse((here.path / "code").is_symlink())
            self.assertEqual(code(here), held)

    def test_the_ak_this_machine_runs_under_code_stays(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            for machine in (home, here):
                machine.write(MAIN, f"{machine.name}'s")
            (here.path / "agentkit").rename(here.path / "code/agentkit")
            (here.path / "agentkit").symlink_to("code/agentkit")
            self.standby(here, home)
            self.assertEqual((here.path / MAIN).read_text(), "acme-mini's")
            self.assertEqual(here.run(".local/bin/ak", "standby", "--help").code, 0)


if __name__ == "__main__":
    unittest.main()

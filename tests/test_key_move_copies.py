"""`ak move ALIAS` copies this home to the same path on the machine `ssh ALIAS` reaches, and a repeat
sends only what changed and deletes there what was deleted here.  Each machine keeps its own of
ak's tmp folder, `~/.ssh/authorized_keys` and the browser profile's lock files; sockets and pipes
are not sent; a file vanishing mid-pass is no failure.  It refuses, changing nothing anywhere, when
ALIAS is this machine, its home has another path, ak's tick is in its crontab or that crontab
fails, or one of those kept is a link or under one, the home itself included, on either machine.

Black-box, through tests/fixtures/akbin.py: the other machine is a second home on this one, which
its ssh binds at this home's path with bubblewrap; its programs are sh, grep and rsync, and a
crontab where a test gives it one.
"""

import os
from pathlib import Path
import shutil
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable

PROFILE = ".local/share/browser-bridge/profile"
KEPT = (".agentkit/tmp", ".ssh/authorized_keys", f"{PROFILE}/SingletonLock")
TICK = "*/3 * * * * /opt/ak/bin/ak watch >>/dev/null 2>&1 # agentkit watch"
# ssh ALIAS COMMAND: COMMAND as the other machine's shell runs it.
SSH = '#!/bin/bash\nshift\nexec {box} /usr/bin/env -i HOME={home} PATH={bin} /bin/bash -c "$*"\n'


def tree(root):
    """Each path under `root`: a file's bytes, a link's target, None for a folder, else `special`."""
    found = {}
    for top, folders, files in os.walk(root):
        for path in (Path(top, name) for name in folders + files):
            found[str(path.relative_to(root))] = (
                f"-> {os.readlink(path)}" if path.is_symlink() else path.read_bytes()
                if path.is_file() else None if path.is_dir() else "special")
    return found


def mirrored(here, there):
    """What the other machine should hold: this home but what is kept, which stays its own."""
    return {**{path: what for path, what in here.items()
               if not path.startswith(KEPT) and what != "special"},
            **{path: what for path, what in there.items() if path.startswith(KEPT)}}


@unittest.skipUnless(boxable(), "no bwrap able to bind the other machine's home here")
class AkMoveCopiesItsHome(unittest.TestCase):
    def machines(self, ssh="another", crontab=None, link=None, gone=None):
        """(home, the other machine's home): each with its own tmp folder, keys and profile lock,
        this one with files of each kind, that one with a file this one never had.  `ssh` is
        `another` machine, this `same` one, or this one with its home `elsewhere`; `link`, (side,
        path), makes that path a link to where it was; `gone` is a folder this home lacks."""
        home = Home()
        self.addCleanup(home.close)
        there, tools = home.root / "there", home.root / "there-bin"
        tools.mkdir()
        for tool in ("sh", "grep", "rsync"):
            (tools / tool).symlink_to(shutil.which(tool))
        if crontab:
            (tools / "crontab").write_text(f"#!/bin/sh\n{crontab}\n")
            (tools / "crontab").chmod(0o755)
        for root, side in ((home.path, "here"), (there, "there")):
            for path in (".agentkit/tmp/watch.log", ".ssh/authorized_keys", f"{PROFILE}/Default/x"):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(side)
            (root / PROFILE / "SingletonLock").symlink_to(f"{side}-1")
        for path in ("notes.txt", "code/api/main.py", ".ssh/config"):
            home.write(path, path)
        (there / "stale").mkdir()
        (there / "stale/old.txt").write_text("deleted here long ago")
        os.mkfifo(home.path / "pipe")
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(home.path / "sock"))
        if gone:
            shutil.rmtree(home.path / gone)
        if link:
            side, path = link
            place = (home.path if side == "here" else there) / path
            place.rename(home.root / "aside")
            place.symlink_to(home.root / "aside")
        # bound where this home is, as bwrap mounts on no link
        box = (f"bwrap --dev-bind / / --bind {there} {home.path.resolve()}" if ssh == "another"
               else "")
        home.fake("ssh", SSH.format(box=box, home=there if ssh == "elsewhere" else home.path,
                                    bin=tools))
        return home, there

    def test_a_pass_mirrors_the_home_and_a_repeat_sends_only_what_changed(self):
        home, there = self.machines(crontab="echo 'MAILTO=\"\"'")
        here, kept = tree(home.path), tree(there)
        done = home.ak("move", "acme-mini")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(tree(home.path), here)
        self.assertEqual(tree(there), mirrored(here, kept))

        home.write("notes.txt", "changed")
        (home.path / "code/api/main.py").unlink()
        (home.root / "there-bin/crontab").unlink()      # a machine with no crontab has no tick
        unchanged = (there / ".ssh/config").stat().st_ino
        here = tree(home.path)
        done = home.ak("move", "acme-mini")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(tree(there), mirrored(here, kept))
        self.assertEqual((there / ".ssh/config").stat().st_ino, unchanged)

    def test_a_file_vanishing_mid_pass_is_no_failure(self):
        home, there = self.machines()
        # rsync's own word for a file gone between its listing and its sending
        home.fake("rsync", f'#!/bin/sh\n{shutil.which("rsync")} "$@" || exit; exit 24\n')
        here, kept = tree(home.path), tree(there)
        done = home.ak("move", "acme-mini")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(tree(there), mirrored(here, kept))

    def test_a_refusal_changes_nothing_anywhere(self):
        for case, setting in {
                "ALIAS is this machine": {"ssh": "same"},
                "its home has another path, and this one no tmp folder":
                    {"ssh": "elsewhere", "gone": ".agentkit/tmp"},
                "the tick is in its crontab": {"crontab": f"echo '{TICK}'"},
                "its crontab fails": {"crontab": "exit 1"},
                "the home is a link here": {"link": ("here", "")},
                "ak's tmp folder is a link here": {"link": ("here", ".agentkit/tmp")},
                "the keys lie under a link there": {"link": ("there", ".ssh")},
                "the profile lies under a link here": {"link": ("here", ".local/share")},
                "the profile is a link there": {"link": ("there", PROFILE)}}.items():
            with self.subTest(case):
                home, there = self.machines(**setting)
                before = tree(home.path), tree(there)
                done = home.ak("move", "acme-mini")
                self.assertNotEqual(done.code, 0, done.out)
                self.assertEqual((tree(home.path), tree(there)), before)


if __name__ == "__main__":
    unittest.main()

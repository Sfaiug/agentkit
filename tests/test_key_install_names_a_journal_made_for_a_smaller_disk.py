"""A server install names a journal smaller than mke2fs makes for its filesystem now.

An ext4 filesystem keeps the journal it was made with, and a cloud image grown at first boot runs
a large disk on a small disk's journal, which only an offline filesystem enlarges.  So while the
filesystem holding ak's home has fewer journal blocks than e2fsprogs gives its block count by
default, each server install prints one note naming the filesystem's size, its journal's, the
default's, and that only an offline filesystem takes a larger one; a journal at or above the
default, a client, or a filesystem that cannot be read gets none.  Black-box: install.sh of the
checkout `AK_BIN` names runs as a server install in a Home that is the account's own
(tests/fixtures/installer.py), with `AK_DEV_BLOCK` a folder holding one file, named
`MAJOR:MINOR` for the device number of the Home's ak home, which a stand-in `dumpe2fs` prints as
that filesystem's header, run by a passwordless stand-in `sudo`, on a PATH reaching no real
dumpe2fs, under LC_ALL=de_DE.UTF-8 where the host has that locale.
"""

import os
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

# Passwordless: it runs `true` and dumpe2fs, after the VAR=value words sudo takes, and refuses
# the rest of what an install asks of root.
SUDO = """#!/bin/sh
[ "$1" = -n ] && shift
for word; do
  case $word in
    *=*) ;;
    true|dumpe2fs) exec env "$@" ;;
    *) break ;;
  esac
done
echo "sudo: not scripted in this test" >&2
exit 1
"""
# `dumpe2fs -h DEVICE` prints the header the file DEVICE holds, as of a filesystem there.
DUMPE2FS = """#!/bin/sh
echo "dumpe2fs 1.47.4 (6-Mar-2025)" >&2
[ "$1" = -h ] && cat -- "$2" || exit 1
exit {code}
"""
GERMAN = "de_DE.UTF-8"
HAS_GERMAN = subprocess.run(
    [sys.executable, "-c", f"import locale; locale.setlocale(locale.LC_ALL, {GERMAN!r})"],
    capture_output=True).returncode == 0


def header(blocks, size, journal, inode=True, total=True):
    """dumpe2fs -h's header of a filesystem of `blocks` blocks of `size` bytes with a journal of
    `journal` blocks: in an inode unless not `inode`, on another device then; that count printed
    unless not `total`."""
    lines = ["Filesystem volume name:   acme-root", f"Block count:              {blocks}",
             "Reserved block count:     0", f"Block size:               {size}",
             "Journal inode:            8" if inode else "Journal device:           0x0803",
             "Journal backup:           inode blocks", "Journal features:         journal_incompat_revoke",
             f"Total journal size:       {journal * size >> 20}M",
             f"Total journal blocks:     {journal}" if total else "",
             f"Max transaction length:   {journal}", "Fast commit length:       0"]
    return "".join(line + "\n" for line in lines if line)


class JournalNote(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        installer.prepare(home)
        installer.own_home(home)
        home.fake("sudo", SUDO)
        self.dumpe2fs(0)
        devices = home.root / "dev/block"
        devices.mkdir(parents=True)
        dev = os.stat(home.path / ".agentkit").st_dev
        self.device = devices / f"{os.major(dev)}:{os.minor(dev)}"
        # no real dumpe2fs for the stand-in sudo to find
        path = [folder for folder in home.env["PATH"].split(os.pathsep)
                if folder == str(home.bin) or not Path(folder, "dumpe2fs").exists()]
        home.env.update(AK_DEV_BLOCK=str(devices), PATH=os.pathsep.join(path),
                        **({"LC_ALL": GERMAN} if HAS_GERMAN else {}))

    def dumpe2fs(self, code):
        self.home.fake("dumpe2fs", DUMPE2FS.format(code=code))

    def notes(self, *args):
        """Each line of a server install's output holding the word journal, but in its paths."""
        done = installer.run(self.home, *(args or ("--server",)))
        self.assertEqual(done.code, 0, done.out + done.err)
        output = (done.out + done.err).replace(str(installer.CHECKOUT), "").replace(str(self.home.root), "")
        return [line for line in output.splitlines() if "journal" in line.lower()]

    def test_a_350_gib_on_a_3_gib_disk_s_journal_is_named_with_the_default_and_offline(self):
        self.device.write_text(header(91750400, 4096, 16384))
        [note] = self.notes()
        for words in ("350 GiB", "64 MiB", "1 GiB", "offline"):
            self.assertIn(words, note)
        self.assertEqual(self.notes(), [note])      # each install, again while it holds

    def test_b_a_size_of_no_whole_gib_is_in_mib(self):
        self.device.write_text(header(393216, 4096, 1024))
        [note] = self.notes()
        self.assertIn("1536 MiB", note)

    def test_c_a_journal_as_large_as_mke2fs_makes_today_is_not_named(self):
        for blocks, size, journal in ((91750400, 4096, 262144), (5242880, 4096, 32768),
                                      (157286400, 1024, 262144)):
            with self.subTest(blocks=blocks, size=size):
                self.device.write_text(header(blocks, size, journal))
                self.assertEqual(self.notes(), [])

    def test_d_what_cannot_be_read_is_not_named(self):
        small = header(91750400, 4096, 16384)
        self.device.write_text(small)
        self.dumpe2fs(1)
        self.assertEqual(self.notes(), [], "a dumpe2fs that failed")
        self.dumpe2fs(0)
        for name, text in (("no Total journal blocks", header(91750400, 4096, 16384, total=False)),
                           ("no Journal inode", header(91750400, 4096, 16384, inode=False))):
            self.device.write_text(text)
            self.assertEqual(self.notes(), [], name)
        self.device.write_text(small)
        self.assertEqual(self.notes("--client", "acme-box"), [], "a client")
        self.home.fake("sudo", "#!/bin/sh\necho 'sudo: a password is required' >&2\nexit 1\n")
        self.assertEqual(self.notes(), [], "no passwordless sudo")
        self.home.fake("sudo", SUDO)
        (self.home.bin / "dumpe2fs").unlink()
        self.assertEqual(self.notes(), [], "no dumpe2fs")
        self.dumpe2fs(0)
        self.device.rename(self.device.with_name("0:0"))     # another device's
        self.assertEqual(self.notes(), [], "no file for the device number")


if __name__ == "__main__":
    unittest.main(verbosity=2)

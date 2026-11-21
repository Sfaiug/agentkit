"""A server install names a journal smaller than mke2fs makes for its filesystem now.

An ext4 filesystem keeps the journal it was made with, and a cloud image grown at first boot runs
a large disk on a small disk's journal, which only an offline filesystem enlarges.  So while the
filesystem holding ak's home has fewer journal blocks than e2fsprogs gives its block count by
default, each server install prints one note naming the filesystem's size, its journal's, the
default's, and that only an offline filesystem takes a larger one, then the e2fsck and tune2fs
commands that give it one, by the UUID dumpe2fs prints where that is 36 hex digits and dashes;
a journal at or above the default, a client, or a filesystem that cannot be read gets none.
Black-box: install.sh of the checkout `AK_BIN` names runs as a server install in a Home that is
the account's own (tests/fixtures/installer.py), with `AK_DEV_BLOCK` a folder holding one file,
named `MAJOR:MINOR` for the device number of the Home's ak home, which a stand-in `dumpe2fs`
prints as that filesystem's header, run by a passwordless stand-in `sudo`, on a PATH reaching no
real dumpe2fs, under LC_ALL=de_DE.UTF-8 where the host has that locale.
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


UUID = "3f6c2a1e-8b4d-4e7a-9c05-d2e1f0a9b7c4"


def header(blocks, size, journal, inode=True, total=True, mounted="/", uuid=UUID):
    """dumpe2fs -h's header of a filesystem of `blocks` blocks of `size` bytes with a journal of
    `journal` blocks: in an inode unless not `inode`, on another device then; that count printed
    unless not `total`; last mounted on `mounted`, printed as it is, as dumpe2fs prints it; its
    UUID `uuid`."""
    lines = ["Filesystem volume name:   acme-root", f"Last mounted on:          {mounted}",
             f"Filesystem UUID:          {uuid}", "Filesystem magic number:  0xEF53",
             f"Block count:              {blocks}", "Reserved block count:     0",
             f"Block size:               {size}",
             "Journal inode:            8" if inode else "Journal device:           0x0803",
             "Journal backup:           inode blocks", "Journal features:         journal_incompat_revoke",
             f"Total journal size:       {journal * size >> 20}M",
             f"Total journal blocks:     {journal}" if total else "",
             f"Max transaction length:   {journal}", "Fast commit length:       0"]
    return "".join(line + "\n" for line in lines if line)


# the fields a note needs, and no Block count line
BARE = "Block size: 4096\nJournal inode: 8\nTotal journal blocks: 16384\n"


@unittest.skipUnless(sys.platform.startswith("linux"), "a Linux server's install")
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
        # no real dumpe2fs on PATH: a folder holding one, as a merged /usr/bin does, gives way to
        # a folder of links to all else it holds
        path = home.env["PATH"].split(os.pathsep)
        for at, folder in enumerate(path):
            if folder != str(home.bin) and Path(folder, "dumpe2fs").exists():
                path[at] = str(home.root / f"path{at}")
                os.mkdir(path[at])
                for program in Path(folder).iterdir():
                    if program.name != "dumpe2fs":
                        Path(path[at], program.name).symlink_to(program)
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
        for words in ("350 GiB", "64 MiB", "1 GiB", "offline", "room"):
            self.assertIn(words, note)
        commands = [note.index(f"{command} UUID={UUID}") for command in
                    ("e2fsck -f", "tune2fs -O ^has_journal", "tune2fs -j")]
        self.assertEqual(commands, sorted(commands))
        self.assertLess(note.index("offline"), commands[0])
        self.assertEqual(self.notes(), [note])      # each install, again while it holds
        # a mount path holding a line like a field's changes no field
        self.device.write_text(header(91750400, 4096, 16384,
                                      mounted="/srv/archive\nBlock size: 1024"))
        self.assertEqual(self.notes(), [note])
        # fields from the first line, and no UUID: the note without its commands
        self.device.write_text("Block count: 91750400\n" + BARE)
        [plain] = self.notes()
        self.assertEqual(note[:len(plain)], plain)
        self.assertNotIn("tune2fs", plain)

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
                           ("no Journal inode", header(91750400, 4096, 16384, inode=False)),
                           ("a journal in a mount path alone", header(
                               91750400, 4096, 16384, inode=False, total=False,
                               mounted="/srv\nJournal inode: 8\nTotal journal blocks: 1")),
                           ("no Block count", "91750400\n" + BARE)):
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

    def test_e_a_uuid_of_other_than_36_hex_digits_and_dashes_names_no_command(self):
        other = "9e1d7b20-4c3a-4f68-b5e2-a07c6d18f3b9"
        for name, kw in (("a space", {"uuid": UUID.replace("-", " ", 1)}),
                         ("more behind it", {"uuid": UUID + ":bad"}),
                         ("another in a mount path",
                          {"mounted": f"/srv\nFilesystem UUID: {other}"}),
                         ("another in a mount path, and an empty one",
                          {"mounted": f"/srv\nFilesystem UUID: {other}", "uuid": ""})):
            self.device.write_text(header(91750400, 4096, 16384, **kw))
            [note] = self.notes()
            self.assertIn("offline", note, name)
            self.assertNotIn("e2fsck", note, name)
            self.assertNotIn("tune2fs", note, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

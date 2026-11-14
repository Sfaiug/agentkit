"""A dead maker's scratch goes whole, what its command closed included, and never through a
link: a link inside goes as a link, and a scratch whose name a link took fails, the folder it
names as it was, as does a folder moved out while it goes.  No depth is too deep for it.  One
whose removal cannot finish keeps its mark, for the next collection.

Offline, in the test's own folder: `gc.clear_scratch`, as a collection calls it once
`gc.left_scratch` names a folder.
"""

import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import gc, record


class ScratchGoesThroughNoLink(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.scratch = root / "runs" / "fix-api" / "tmp-left"
        self.scratch.mkdir(parents=True)
        (self.scratch / record.SCRATCH).write_text(json.dumps({"pid": 99999999}))
        self.outside = root / "acme"
        self.outside.mkdir(mode=0o750)
        (self.outside / "notes.txt").write_text("kept\n")

    def closed(self, mode):
        """A folder in the scratch holding a file, its mode then `mode`."""
        folder = self.scratch / ".box-1" / "closed"
        folder.mkdir(parents=True)
        (folder / "payload").write_text("scratch\n")
        folder.chmod(mode)

    def assertOutsideAsItWas(self):
        self.assertEqual((self.outside / "notes.txt").read_text(), "kept\n")
        self.assertEqual(self.outside.stat().st_mode & 0o777, 0o750)

    def test_it_goes_whole_and_a_link_inside_goes_as_a_link(self):
        self.closed(0o000)
        (self.scratch / "acme").symlink_to(self.outside, target_is_directory=True)
        gc.clear_scratch(self.scratch)
        self.assertFalse(self.scratch.exists())
        self.assertOutsideAsItWas()

    def test_a_name_a_link_took_fails_and_leaves_what_it_names(self):
        self.scratch.rename(self.scratch.with_name("tmp-moved"))
        self.scratch.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(OSError):
            gc.clear_scratch(self.scratch)
        self.assertOutsideAsItWas()

    def test_a_tree_deeper_than_the_recursion_and_open_file_limits_goes_whole(self):
        folder = self.scratch
        for _ in range(sys.getrecursionlimit() + 100):
            folder /= "d"
            folder.mkdir()
        (folder / "payload").write_text("scratch\n")
        limits = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, limits[1]))
        try:
            gc.clear_scratch(self.scratch)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, limits)
        self.assertFalse(self.scratch.exists())

    def test_a_folder_moved_out_while_it_goes_fails_and_keeps_where_it_went(self):
        inner = self.scratch / "a" / "b"
        inner.mkdir(parents=True)
        listdir = os.listdir

        def moving(fd):
            if inner.exists() and os.path.samestat(os.fstat(fd), inner.stat()):
                inner.rename(self.outside / "b")
            return listdir(fd)

        with patch("os.listdir", moving), self.assertRaises(OSError):
            gc.clear_scratch(self.scratch)
        self.assertTrue((self.outside / "b").is_dir())
        self.assertOutsideAsItWas()

    def test_one_whose_removal_cannot_finish_keeps_its_mark(self):
        self.closed(0o500)
        with patch("os.rmdir", side_effect=PermissionError(13, "held")), \
                self.assertRaises(OSError):
            gc.clear_scratch(self.scratch)
        self.assertTrue((self.scratch / record.SCRATCH).is_file())

    def test_one_whose_own_folder_cannot_go_keeps_its_mark(self):
        (self.scratch / "payload").write_text("scratch\n")
        with patch("os.rmdir", side_effect=PermissionError(13, "held")), \
                self.assertRaises(OSError):
            gc.clear_scratch(self.scratch)
        self.assertEqual(os.listdir(self.scratch), [record.SCRATCH])
        self.assertEqual(json.loads((self.scratch / record.SCRATCH).read_text()),
                         {"pid": 99999999})


if __name__ == "__main__":
    unittest.main()

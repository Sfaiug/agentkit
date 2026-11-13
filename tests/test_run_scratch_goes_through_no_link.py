"""A dead maker's scratch goes whole, what its command closed included, and never through a
link: a link inside goes as a link, and a scratch whose name a link took fails, the folder it
names as it was.  One whose removal cannot finish keeps its mark, for the next collection.

Offline, in the test's own folder: `gc.clear_scratch`, as a collection calls it once
`gc.left_scratch` names a folder.
"""

import json
from pathlib import Path
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

    def test_one_whose_removal_cannot_finish_keeps_its_mark(self):
        self.closed(0o500)
        with patch("os.rmdir", side_effect=PermissionError(13, "held")), \
                self.assertRaises(OSError):
            gc.clear_scratch(self.scratch)
        self.assertTrue((self.scratch / record.SCRATCH).is_file())


if __name__ == "__main__":
    unittest.main()

"""A menu starting itself again on new code hands its last read over the exec (`warm.hand_on`),
and the new program takes it where the same code made it, or else reads as if none came
(`warm.handed`).  In-process: nothing is exec'd here, which
tests/test_key_new_code_leaves_the_screen_up.py does from outside.
"""

import os
from pathlib import Path
import pickle
import sys
import tempfile
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import warm  # noqa: E402

READ = [[{"name": "acme"}], ([{"name": "acme"}], [], 0, 0)]


class HandedOn(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("AK_MENU_READ", None)

    def holding(self, data):
        """The variable set to a descriptor holding `data`, as the exec would leave it."""
        fd, path = tempfile.mkstemp()
        os.unlink(path)
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
        os.environ["AK_MENU_READ"] = str(fd)
        return fd

    def gone(self, fd):
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertNotIn("AK_MENU_READ", os.environ)

    def test_the_same_code_takes_the_read_and_closes_the_descriptor(self):
        env = warm.hand_on(READ, "code")
        self.assertEqual(list(env), ["AK_MENU_READ"])
        fd = int(env["AK_MENU_READ"])
        self.assertTrue(os.get_inheritable(fd))      # the exec keeps it
        self.assertEqual(os.fstat(fd).st_nlink, 0)   # and no name reaches it
        self.assertNotIn("AK_MENU_READ", os.environ)      # the caller adds it to the exec's alone
        os.environ.update(env)
        self.assertEqual(warm.handed("code"), READ)
        self.gone(fd)

    def test_other_code_reads_as_if_none_came(self):
        os.environ.update(env := warm.hand_on(READ, "code"))
        self.assertIsNone(warm.handed("other"))
        self.gone(int(env["AK_MENU_READ"]))

    def test_a_closed_descriptor_is_none(self):
        fd = self.holding(b"")
        os.close(fd)
        self.assertIsNone(warm.handed("code"))
        self.gone(fd)

    def test_what_is_no_read_is_none(self):
        for data in (b"", b"garbage", pickle.dumps(5), pickle.dumps([])):
            with self.subTest(data=data):
                fd = self.holding(data)
                self.assertIsNone(warm.handed("code"))
                self.gone(fd)

    def test_a_variable_naming_no_descriptor_is_none(self):
        os.environ["AK_MENU_READ"] = "not a number"
        self.assertIsNone(warm.handed("code"))
        self.assertNotIn("AK_MENU_READ", os.environ)

    def test_no_variable_is_none(self):
        self.assertIsNone(warm.handed("code"))

    def test_a_read_that_cannot_be_handed_on_stops_no_restart(self):
        self.assertEqual(warm.hand_on([lambda: None, None], "code"), {})    # no pickle of it
        with patch.object(tempfile, "mkstemp", side_effect=OSError("no room")):
            self.assertEqual(warm.hand_on(READ, "code"), {})


if __name__ == "__main__":
    unittest.main()

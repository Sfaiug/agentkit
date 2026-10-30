"""A suite the helper has room for runs there alone, though this host has turns free.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py; the helper is a fake ssh with room for two VMs, whose pieces pass there.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line

# The words after the alias are one `bash -c <mac.sh> mac.sh <verb> ...` line.
SSH = f"""#!{sys.executable}
import shlex, sys
words = shlex.split(sys.argv[-1])
verb = words[words.index("mac.sh") + 1]
if verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
"""


class SuiteOnAHelper(unittest.TestCase):
    def test_no_piece_of_it_runs_here(self):
        line = Line({"t/a.sh": "true\n", "t/b.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        line.home.env["AK_MAX_RUNS"] = ""    # this host has turns to give
        line.home.fake("ssh", SSH)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1))
        self.assertEqual(line.runs(), [])


if __name__ == "__main__":
    unittest.main()

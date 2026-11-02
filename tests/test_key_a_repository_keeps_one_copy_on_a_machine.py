"""Suites from two clones of one repository name one copy of its history on the suite helper.

Each clone named its own, so one machine held 169 and filled up (2 Nov 2026).  Black-box, as
test_key_a_suite_is_cut_for_the_whole_machine.py: the helper is a fake ssh with plenty of room that
writes down the repository each `prepare` names.
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
verb, *args = words[words.index("mac.sh") + 1:]
if verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
    with open({{named!r}}, "a") as named:
        named.write(args[2] + "\\n")
"""


class ARepositoryKeepsOneCopy(unittest.TestCase):
    def test_suites_from_two_clones_name_one_copy(self):
        line = Line({"t/a.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        named = line.home.root / "named"
        line.home.fake("ssh", SSH.format(named=str(named)))
        for n, clone in enumerate(("acme-one", "acme-two"), 1):
            # A line of its own: a line's checks run from its first member's checkout.
            line.line, line.rig.path = f".merge-{clone}.lock", line.home.path / "code" / clone
            line.home.run("git", "clone", "-q", str(line.rig.bare), str(line.rig.path))
            line.member({f"api{n}.txt": "x\n"})
            done = line.land()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertIn("land", line.verdict(n))
        self.assertEqual(len(set(named.read_text().split())), 1, named.read_text())


if __name__ == "__main__":
    unittest.main()

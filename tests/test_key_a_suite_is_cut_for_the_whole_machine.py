"""A suite that starts on a nearly full suite helper is cut for that whole machine.

Cut into twice the places it starts with, it would stay in two pieces however much room frees
there; cut into twice the VMs the helper fits empty, it starts on the room there is and grows
into what frees.  Black-box, as test_key_helper_red_never_skips_the_rest_of_its_piece.py: the
helper is a fake ssh with 8 CPUs, a load of 6 and plenty of memory, so one VM of two CPUs fits
now and four empty.
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
    print("cpus 8\\nload 6\\nroom_mb 524288")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run":
    with open({{asked!r}}, "a") as asked:
        asked.write(args[6] + "\\n")
"""


class ASuiteIsCutForTheWholeMachine(unittest.TestCase):
    def test_a_suite_starting_on_one_free_place_there_is_cut_in_eight(self):
        line = Line({"t/a.sh": "true\n", "t/b.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        asked = line.home.root / "asked"
        line.home.fake("ssh", SSH.format(asked=str(asked)))
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1))
        pieces = {share for share in asked.read_text().split() if share != "1/1"}
        self.assertEqual(pieces, {f"{k}/8" for k in range(1, 9)})


if __name__ == "__main__":
    unittest.main()

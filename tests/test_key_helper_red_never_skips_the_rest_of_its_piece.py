"""A piece red on the suite helper is green only once the whole piece passes here.

The helper's runner stops at its first failure, naming that one test: passing alone here says
nothing of the tests it never reached, so the whole piece runs here and decides.  Black-box: the
program `AK_BIN` names checks a landing line from outside through tests/fixtures/akline.py; the
helper is a fake ssh with room for one VM, whose two pieces fail there naming `a.sh`.
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
    print("cpus 2\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run":
    print("FAIL a.sh")
    sys.exit(1)
elif verb == "failed":
    print("a.sh")
"""


class HelperRedNeverSkipsTheRestOfItsPiece(unittest.TestCase):
    def land(self, b):
        """What the lander left its one member waiting on, and its suite's runs, where `t/b.sh`,
        a test the helper never reached, is `b`."""
        line = Line({"t/a.sh": "true\n", "t/b.sh": b,
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        line.home.fake("ssh", SSH)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.said = "".join(path.read_text(errors="replace")
                            for path in (line.home.path / ".agentkit").rglob("*.log"))
        return line.verdict(1), line.runs()

    def test_a_test_the_helper_never_reached_failing_here_keeps_it_red(self):
        verdict, runs = self.land("! test -f api.txt\n")    # red on the member's tree alone
        self.assertIn("fix", verdict, verdict)
        self.assertEqual(runs[:3], [("alone", ""), ("alone", ""), ("piece", "1/2", "")])

    def test_a_piece_red_only_on_the_helper_passing_whole_here_is_a_flake_of_the_helper(self):
        verdict, runs = self.land("true\n")
        self.assertIn("land", verdict, verdict)
        self.assertEqual(runs, [("alone", "")] * 2 + [("piece", f"{k}/2", "") for k in (1, 2)])
        self.assertIn("failed on the suite helper acme-mac, then passed on its re-run",
                      self.said)


if __name__ == "__main__":
    unittest.main()

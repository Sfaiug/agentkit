"""A red check's confirmed pieces are tried before the next whole check: once narrowing blames a
member, each piece the last red whole check confirmed runs just its tests on the stack rebuilt
without it, and one failing there is narrowed to its member before any stack is checked whole
again.  So two culprits cost the suite three whole runs: on the deepest stack, on the stack below
the last culprit and on the top rebuilt without both; checking each rebuilt top whole cost five.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its suite cut in pieces so that each test runs in the piece its name
begins with, however many pieces there are.  Of six members the second and the fourth each break
a test; so too, where the stacks rebuilt without the first culprit all fit side by side, do the
first and the third of four whose tasks run that suite as their own check.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, SUITE, Line, rules

PIECES = RUNNER.replace('[ $((i % n + 1)) = "$k" ]', '[ $(((${t%%-*} - 1) % n + 1)) = "$k" ]')
# Each test fails on a tree holding the file its name ends with.
TESTS = {f"t/{name}.sh": f"test ! -f {name.split('-')[1]}.txt\n"
         for name in ("1-a", "1-b", "2-c", "3-d")}


class ARedCheckSPiecesAreTriedBeforeTheNextWholeCheck(unittest.TestCase):
    def land(self, broken, count=6, once=False):
        """One pass over `count` members, member n breaking test `broken[n]`: each sent back,
        told its own test, the others landing.  With `once` the target's suite is `true` and
        each member's task runs the pieces' suite as its `# once` check, and as many whole
        checks fit side by side as there are stacks rebuilt without the first member."""
        self.assertNotEqual(PIECES, RUNNER)
        line = Line({**TESTS, "suite.sh": PIECES, **({"AGENTS.md": rules("true")} if once else {})})
        self.addCleanup(line.close)
        if once:
            config = line.home.path / ".agentkit" / "config.toml"
            config.write_text(f"max_gates = {count - 1}\n" + config.read_text())
        for n in range(1, count + 1):
            line.member({f"member-{n}.txt": f"{n}\n",
                         **({f"{broken[n].split('-')[1]}.txt": "x\n"} if n in broken else {})})
            if once:
                (line.members[-1] / "task.md").write_text(
                    f"# fix-{n}\n\n## Done when\n```bash\n{SUITE}  # once\n```\n")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, count + 1):
            wait = line.verdict(n)
            self.assertEqual([key for key in ("land", "fix") if key in wait],
                             ["fix"] if n in broken else ["land"], (n, line.runs()))
            if n in broken:
                self.assertEqual(wait["fix"]["tests"], [f"{broken[n]}.sh"], line.runs())
        return line

    def test_two_culprits_in_two_pieces_cost_three_whole_runs(self):
        line = self.land({2: "1-a", 4: "2-c"})
        self.assertEqual(line.whole(), 3, line.runs())

    def test_two_culprits_in_one_piece_cost_three_whole_runs(self):
        line = self.land({2: "1-a", 4: "1-b"})
        self.assertEqual(line.whole(), 3, line.runs())

    def test_it_does_too_where_the_rebuilt_stacks_all_fit_side_by_side(self):
        line = self.land({1: "1-a", 3: "2-c"}, count=4, once=True)
        self.assertEqual(line.whole(), 3, line.runs())


if __name__ == "__main__":
    unittest.main()

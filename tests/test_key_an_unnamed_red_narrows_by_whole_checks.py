"""A red piece that named no test is narrowed by whole checks, never by its number: the suite
deals each tree's own test files into its pieces, so on a stack with a member less the piece
of that number holds other tests.  A member goes to its fixer only where its own stack's whole
check ran red and the stack just ahead of it passed whole.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its suite dealing each tree's test files into its pieces in name
order and failing a piece before naming any test where one of its files cannot be loaded.  Of
six members the second adds a test loading api.sh, the third removes api.sh, and each later
one adds a test sorting ahead of the second's, so the piece holding it has another number on
every stack.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, Line

# Each piece logs the stack it runs on, then loads its tests as an import would, sourcing
# each: one that cannot be loaded fails the piece before any test is named.
LOADS = RUNNER.replace('echo "piece $share $*" >>"$log";', '''echo "piece $share $*" >>"$log"
  echo "$share $(echo member-*)" >>"${log%/*}/stacks";''').replace("code=0\n", '''
for t in $tests; do [ ! -f "t/$t" ] || (. "./t/$t") >/dev/null || exit 1; done
code=0
''')
TESTS = {"suite.sh": LOADS, "api.sh": ":\n", **{f"t/c{n}.sh": "true\n" for n in range(1, 9)}}


class AnUnnamedRedNarrowsByWholeChecks(unittest.TestCase):
    def test_the_member_breaking_a_file_its_piece_loads_is_found_by_whole_checks(self):
        line = Line(TESTS)
        self.addCleanup(line.close)
        changes = {2: {"t/b.sh": ". ./api.sh\n"}, 3: {"api.sh": None},
                   **{n: {f"t/a{n}.sh": "true\n"} for n in (4, 5, 6)}}
        for n in range(1, 7):
            line.member({f"member-{n}.txt": f"{n}\n", **changes.get(n, {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        stacks = {}
        for share, *members in (row.split(" ") for row in
                                (line.rig.path / ".git" / "stacks").read_text().splitlines()):
            stacks.setdefault(frozenset(members), set()).add(share)
        for n in range(1, 7):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 3 else ["land"], (n, stacks))
        self.assertNotIn("tests", line.verdict(3)["fix"])
        # every stack that ran a piece ran every piece: a whole check, never one alone
        pieces = set().union(*stacks.values())
        self.assertGreater(len(pieces), 3, stacks)
        for members, shares in stacks.items():
            self.assertEqual(shares, pieces, (members, stacks))
        # the culprit's own stack was checked whole, and so was the one just ahead of it
        self.assertIn(frozenset(f"member-{n}.txt" for n in (1, 2, 3)), stacks)
        self.assertIn(frozenset(f"member-{n}.txt" for n in (1, 2)), stacks)


if __name__ == "__main__":
    unittest.main()

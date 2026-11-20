"""The split run also makes a suite name its tests: the check its task hands out (`ak pieces`)
passes a branch whose `tests:` line, run as three pieces at once, names what each ran (`AK_RAN`)
and, given a test a piece named and one none did (`AK_ONLY`), runs just the first and names the
second as not there (`AK_NOT_THERE`), whichever piece holds its tests and however it spells
them; it fails one naming nothing, ignoring AK_ONLY, naming no test as not there or the one it
ran too, as it fails one whose pieces can run only one after another or whose piece fails.

Black-box: `AK_BIN` runs the check in a project folder whose AGENTS.md declares a shell suite,
so no suite has to run two minutes for a task to hand the check out.
"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

# Tests a, b, c and d, all in piece HOLDER of three and in a single piece, each piece running
# once all have started, or just those AK_ONLY lists; naming each it runs and each it lacks.
NAMING = """k=${AK_SHARD%/*} n=${AK_SHARD#*/}
if [ -n "${AK_ONLY:-}" ]; then tests=$(cat "$AK_ONLY"); else
  touch "started-$k"; tries=0
  while [ "$(ls started-* | wc -l)" -lt "$n" ]; do
    tries=$((tries + 1)); [ "$tries" -lt 300 ] || { echo "piece $k ran alone" >&2; exit 1; }
    sleep 0.1
  done
  case $k/$n in HOLDER/3|1/1) tests="a b c d" ;; *) tests= ;; esac
fi
for t in $tests; do
  case $t in
    a|b|c|d) echo "$t" >>"${AK_RAN:-/dev/null}" ;;
    *) echo "$t" >>"${AK_NOT_THERE:-/dev/null}" ;;
  esac
done
"""
# Piece 2/3 runs the two tests `names` prints, or just those AK_ONLY lists of them, each named as
# written, and names the rest as not there; no piece writes a file another reads.
VERBATIM = """names() { printf 'parses a space \\n  keeps its indent\\n'; }
if [ -n "${AK_ONLY:-}" ]; then
  names | grep -Fxf /dev/stdin "$AK_ONLY" >"$AK_RAN"
  names | grep -vFxf /dev/stdin "$AK_ONLY" >"$AK_NOT_THERE"
elif [ "$AK_SHARD" = 2/3 ]; then names >"$AK_RAN"; fi
"""


class TheSplitRunAlsoMakesASuiteNameItsTests(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def check(self, suite, holder=3):
        project = Path(tempfile.mkdtemp(prefix="acme-", dir=self.home.root))
        (project / "AGENTS.md").write_text("---\ntests: sh suite.sh # AK_SHARD\n---\n")
        (project / "suite.sh").write_text(suite.replace("HOLDER", str(holder)))
        return self.home.ak("pieces", cwd=project)

    def test_a_suite_naming_its_tests_passes_whichever_piece_holds_them(self):
        for holder in (1, 2, 3):
            done = self.check(NAMING, holder)
            self.assertEqual(done.code, 0, (holder, done.err))
        done = self.check(VERBATIM)
        self.assertEqual(done.code, 0, done.err)

    def test_a_suite_that_names_no_test_it_ran_fails(self):
        unnamed = NAMING.replace('"${AK_RAN:-/dev/null}"', "/dev/null")
        self.assertNotEqual(self.check(unnamed).code, 0)

    def test_a_suite_running_everything_whatever_ak_only_lists_fails(self):
        self.assertNotEqual(self.check(NAMING.replace('[ -n "${AK_ONLY:-}" ]', "false")).code, 0)

    def test_a_suite_that_names_no_test_it_lacks_fails(self):
        unnamed = NAMING.replace('"${AK_NOT_THERE:-/dev/null}"', "/dev/null")
        self.assertNotEqual(self.check(unnamed).code, 0)
        both = NAMING.replace('tests=$(cat "$AK_ONLY")',
                              'tests=$(cat "$AK_ONLY"); cp "$AK_ONLY" "$AK_NOT_THERE"')
        self.assertNotEqual(self.check(both).code, 0)

    def test_pieces_holding_one_file_or_a_failing_piece_fail(self):
        shared = NAMING.replace('touch "started-$k";', 'touch "started-$k"; mkdir held || exit 1;')
        self.assertNotEqual(self.check(shared).code, 0)
        self.assertNotEqual(self.check(NAMING + '[ "$AK_SHARD" != 2/3 ] || exit 1\n').code, 0)


if __name__ == "__main__":
    unittest.main()

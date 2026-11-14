"""A red test's search starts at the first stack that holds its file: no stack below it can fail
the test, so those count as passing it and nothing runs there.  The member whose stack is the
first to hold it and fails it is blamed, and the suite runs whole only on the top and on the top
rebuilt without that member.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, with a `suite.sh` of its own: its tests are named by their paths in
the tree (`t/new.sh`), or by a spelling naming the same file on disk (`t//new.sh`), and a listed
test whose file is missing is named nowhere, the run failing as one that ran no test does.  Of
six members the fourth adds a test file that fails.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

SUITE = """share=${AK_SHARD:-1/1}; k=${share%/*}; n=${share#*/}
log="$(git rev-parse --git-common-dir)/suite.log"
if [ -n "${AK_ONLY:-}" ]; then echo "alone $*" >>"$log"; tests=$(cat "$AK_ONLY")
else echo "piece $share $*" >>"$log"; tests=; i=0
  for t in t/*; do [ $((i % n + 1)) = "$k" ] && tests="$tests $t"; i=$((i + 1)); done; fi
code=0
for t in $tests; do
  [ -f "$t" ] || { echo "no tests ran"; exit 5; }
  echo "$t" >>"${AK_RAN:-/dev/null}"
  sh "$t" || { echo "FAIL $t"; echo "$t" >>"${AK_FAILED:-/dev/null}"; code=1; }
done
exit $code
"""


class ARedTestSSearchStartsWhereItsFileDoes(unittest.TestCase):
    def test_no_stack_below_the_file_is_checked_whole(self):
        for listed in ("t/", "t//"):
            with self.subTest(listed=listed):
                line = Line({"suite.sh": SUITE.replace("t/*", f"{listed}*"), "t/ok.sh": "true\n"})
                self.addCleanup(line.close)
                for n in range(1, 7):
                    line.member({f"member-{n}.txt": f"{n}\n",
                                 **({"t/new.sh": "false\n"} if n == 4 else {})})
                done = line.land()
                self.assertEqual(done.code, 0, done.out + done.err)
                for n in range(1, 7):
                    self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                                     ["fix"] if n == 4 else ["land"], (n, line.runs()))
                self.assertEqual(line.verdict(4)["fix"]["tests"], [f"{listed}new.sh"],
                                 line.runs())
                # the top, red; the top rebuilt without the fourth, green
                self.assertEqual(line.whole(), 2, line.runs())


if __name__ == "__main__":
    unittest.main()

"""Every answer key Go's ak claims passes on Go, judged from a tree without Python ak.

go/keys.txt lists the claims, one key file per line, followed, where Go passes only part of it,
by the classes or tests it passes as unittest names them.  go/bin/ak is built in a copy of the
checkout's files that leaves out agentkit/, and each claim runs there, so a key that imports
agentkit, or hands Python code that does, fails.  Only what it lists runs: every key against Go
would cost every landing the deadlines of each key whose verb Go lacks.

    python3 tests/test_go_keys.py [test_key_name ...]

Key file names keep it to those files' claims, and one go/keys.txt does not list fails.  With
AK_BIN set it judges that program, a relative name read from the checkout, instead of building.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_go import ENV

REPO = Path(__file__).resolve().parents[1]
# Another file of the suite may be writing or removing the rest of these as this copies.
LEFT_OUT = shutil.ignore_patterns("agentkit", ".git", "__pycache__", ".ak-test-*")
# A skip exits 0 and a file with no test may too: only unittest's tally tells, as every_file.py
# reads it.
PASSED = re.compile(r"^Ran [1-9]\d* tests? in .*\n\nOK$", re.MULTILINE)


class Claims(unittest.TestCase):
    def test_each_claim_passes(self):
        claims = {name: parts for name, *parts in
                  map(str.split, (REPO / "go/keys.txt").read_text().splitlines())}
        asked = sys.argv[1:] or claims
        self.assertFalse(set(asked) - set(claims), "go/keys.txt does not list these")
        named = os.environ.get("AK_BIN")
        with tempfile.TemporaryDirectory(prefix="ak-go-keys-") as tree:
            shutil.copytree(REPO, tree, ignore=LEFT_OUT, symlinks=True, dirs_exist_ok=True)
            program = REPO / named if named else Path(tree, "go/bin/ak")
            if not named:
                # Never a skip: the landing suite counts a skipped case as passed.
                built = subprocess.run(["go", "build", "-o", program, "./cmd/ak"], env=ENV,
                                       cwd=Path(tree, "go"), capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stderr)
            failed = []
            # One after another: every_file.py already runs other files beside this one.  No
            # PYTHONPATH: the caller's could lead back to agentkit.
            for name in asked:
                done = subprocess.run([sys.executable, f"tests/{name}.py", *claims[name]], cwd=tree,
                                      env={**os.environ, "AK_BIN": str(program), "PYTHONPATH": ""},
                                      capture_output=True, text=True)
                if done.returncode or not PASSED.search(done.stderr):
                    claim = " ".join((name, *claims[name]))
                    print(f"--- {claim}\n{done.stdout}{done.stderr}", flush=True)
                    failed.append(claim)
        self.assertFalse(failed, "these claims of go/keys.txt fail or skip")


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=2)

"""Every answer key Go's ak claims passes on Go, judged from a tree without Python ak.

go/keys.txt lists the claims, one key file per line in name order, so milestones landing side by
side add theirs at lines apart, each followed, where Go passes only part of it, by the classes
or tests it passes as unittest names them.  go/bin/ak is built in a copy of the
checkout's files that leaves out agentkit/, and each claim runs there, so a key that imports
agentkit, or hands Python code that does, fails.  Only what it lists runs: every key against Go
would cost every landing the deadlines of each key whose verb Go lacks.

    python3 tests/test_go_keys.py [test_key_name ...]

Key file names keep it to those files' claims, and one go/keys.txt does not list fails, naming
no failing part, as it ran nowhere; without names every claim runs, as the suite's pieces of it
name theirs (every_file.py).  With AK_BIN set it judges that program, a relative name read from
the checkout, instead of building; it builds nothing where no claim runs.
Each failing claim is named by its key file's name in the file FAILED_PARTS names: a piece
takes minutes, so every_file.py's re-run, and a narrowing step on that claim, run it alone.
Each passing one's seconds are in the file PART_TIMES names: they cut the next suite's pieces.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from suite_shares import claims, name_failed, name_timed
from test_go import ENV

REPO = Path(__file__).resolve().parents[1]
# Another file of the suite may be writing or removing the rest of these as this copies.
LEFT_OUT = shutil.ignore_patterns("agentkit", ".git", "__pycache__", ".ak-test-*")
# A skip exits 0 and a file with no test may too: only unittest's tally tells, as every_file.py
# reads it.  The claim's own is the last: a tally of a child it ran comes before.
PASSED = re.compile(r"^Ran [1-9]\d* tests? in .*\n\nOK\n\Z", re.MULTILINE)


@contextmanager
def checkout(build):
    """A copy of the checkout without agentkit/ for keys to run in, the program they judge, and
    its build: AK_BIN's program, a relative name read from the checkout, else go/bin/ak, built
    there when `build`.  The build is None where none ran."""
    named = os.environ.get("AK_BIN")
    # In the checkout, as the suite's other sandboxes are: a key keeping its Home under its
    # checkout counts on that lying outside the temporary places a worker's box makes its own.
    with tempfile.TemporaryDirectory(prefix=".ak-test-go-keys-", dir=REPO) as tree:
        shutil.copytree(REPO, tree, ignore=LEFT_OUT, symlinks=True, dirs_exist_ok=True)
        program = REPO / named if named else Path(tree, "go/bin/ak")
        # Trimmed, a build in this piece's own tree finds what others cached (every_file).
        built = subprocess.run(["go", "build", "-o", program, "-trimpath", "./cmd/ak"], env=ENV,
                               cwd=Path(tree, "go"), capture_output=True,
                               text=True) if build and not named else None
        # a checkout, as Go finds the one it runs from (config.Repo), without the history
        subprocess.run(["git", "init", "-q", tree], check=True)
        yield tree, program, built


def run(tree, program, name, *parts, **env):
    """Key file `name`'s `parts` run in `tree` against `program`, `env` added to this process's
    environment, and whether they passed."""
    # No PYTHONPATH: the caller's could lead back to agentkit.
    done = subprocess.run([sys.executable, f"tests/{name}.py", *parts], cwd=tree,
                          env={**os.environ, "AK_BIN": str(program), "PYTHONPATH": "", **env},
                          capture_output=True, text=True)
    return done, not done.returncode and bool(PASSED.search(done.stderr))


class Claims(unittest.TestCase):
    def test_each_claim_passes(self):
        asked = sys.argv[1:]
        listed = [claim for claim in claims(REPO) if not asked or claim[0] in asked]
        # One it does not list ran nowhere, as one only a later change adds: it fails this file
        # naming no failing part, and those it lists still run.
        unlisted = set(asked) - {claim[0] for claim in listed}
        with checkout(build=bool(listed)) as (tree, program, built):
            if built and built.returncode:
                # Go that does not build fails every claim asked of it, never as a skip: the
                # landing suite counts a skipped case as passed.  Named, a landing's narrowing
                # finds the change that broke the build: unnamed, the claim proves nothing on
                # each stack holding that change (land._probe).
                name_failed([name for name, *_ in listed], "FAILED_PARTS")
                self.fail(built.stderr)
            failed, took = [], {}
            # One after another: every_file.py already runs other files beside this one.
            for name, *parts in listed:
                began = time.monotonic()
                done, passed = run(tree, program, name, *parts)
                took[name] = time.monotonic() - began
                if not passed:
                    failed.append(" ".join((name, *parts)))
                    print(f"--- {failed[-1]}\n{done.stdout}{done.stderr}", flush=True)
        failing = [claim.split()[0] for claim in failed]
        name_failed(failing, "FAILED_PARTS")
        name_timed({name: seconds for name, seconds in took.items() if name not in failing})
        self.assertFalse(unlisted, "go/keys.txt does not list these")
        self.assertFalse(failed, "these claims of go/keys.txt fail or skip")


if __name__ == "__main__":
    # The claims' names are Claims' own arguments, never unittest's.
    unittest.main(argv=sys.argv[:1], verbosity=2)

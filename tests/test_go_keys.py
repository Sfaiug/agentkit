"""Every answer key Go's ak claims passes on Go, judged from a tree without Python ak.

go/keys.txt lists the claims, one key file per line in name order, so milestones landing side by
side add theirs at lines apart, each followed, where Go passes only part of it, by the classes
or tests it passes as unittest names them.  go/bin/ak is built in a copy of the
checkout's files that leaves out agentkit/, and each claim runs there, so a key that imports
agentkit, or hands Python code that does, fails.  Only what it lists runs: every key against Go
would cost every landing the deadlines of each key whose verb Go lacks.

    python3 tests/test_go_keys.py [test_key_name ...]

Key file names keep it to those files' claims, and one go/keys.txt does not list fails, named
in the file NOT_THERE names and as no failing part, as it ran nowhere; without names every claim
runs, as the suite's pieces of it name theirs (every_file.py).  With AK_BIN set it judges that
program, a relative name read from the checkout, instead of building; it builds nothing where no
claim runs.  A claim is judged in a copy shaped like the commit switching ak to Go, as
AK_GO_ALONE=1 asks of checkout() and of tests/fixtures/akbin.py's Home, so one passing only by
what that commit drops fails: its hooks/, adapters/, tools/ and install.sh are go/'s but for the
shell KEPT names, its bin/ holds only the program judged, and the Home refuses Python.  A key file
go/leans/ names still leans on Python's files: its claims are judged in a copy as checked out, with
no AK_GO_ALONE, and the list only shrinks (tests/test_go_leans.py).  With AK_GO_ALONE=1 each claim
is judged switched, named or not, as the switch's own gate judges them and a milestone shows a
lean gone.  The claims judged one way share one copy and one build.
Each failing claim is named by its key file's name in the file FAILED_PARTS names: a piece
takes minutes, so every_file.py's re-run, and a narrowing step on that claim, run it alone.
Each passing one's seconds are in the file PART_TIMES names as it passes: every_file.py prints
its line then, so a piece is silent only while one claim runs, and they cut the next suite's pieces.
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
from unittest.mock import patch

from suite_shares import claims, name_failed, name_timed
from test_go import ENV

REPO = Path(__file__).resolve().parents[1]
# Another file of the suite may be writing or removing the rest of these as this copies.
LEFT_OUT = shutil.ignore_patterns("agentkit", ".git", "__pycache__", ".ak-test-*")
# A skip exits 0 and a file with no test may too: only unittest's tally tells, as every_file.py
# reads it.  The claim's own is the last: a tally of a child it ran comes before.
PASSED = re.compile(r"^Ran [1-9]\d* tests? in .*\n\nOK\n\Z", re.MULTILINE)
# The folders the commit switching ak to Go takes from go/, as it takes install.sh (AK_GO_ALONE).
SWITCHED = ("hooks", "adapters", "tools")
# What that commit keeps of Python's tools/: shell run on another machine, or by git as its merge
# driver, that Go does not replace.  A key playing such a machine reads the helper's from here.
KEPT = ("tools/helper", "tools/machine.sh", "tools/linux-machine.sh", "tools/merge")


def leaning(root):
    """The key files go/leans/ at `root` names, an empty file each: none where it is not there."""
    return {lean.name for lean in Path(root, "go/leans").glob("*")}


@contextmanager
def checkout(build):
    """A copy of the checkout without agentkit/ for keys to run in, the program they judge, and
    its build: AK_BIN's program, a relative name read from the checkout, else go/bin/ak, built
    there when `build`.  With AK_GO_ALONE=1 the copy is switched, and the program its bin/ak,
    built there or a copy of AK_BIN's.  The build is None where none ran."""
    named = os.environ.get("AK_BIN")
    alone = os.environ.get("AK_GO_ALONE") == "1"
    # In the checkout, as the suite's other sandboxes are: a key keeping its Home under its
    # checkout counts on that lying outside the temporary places a worker's box makes its own.
    with tempfile.TemporaryDirectory(prefix=".ak-test-go-keys-", dir=REPO) as tree:
        shutil.copytree(REPO, tree, ignore=LEFT_OUT, symlinks=True, dirs_exist_ok=True)
        program = (Path(tree, "bin/ak") if alone else
                   REPO / named if named else Path(tree, "go/bin/ak"))
        if alone:
            switch(Path(tree))
            if named:
                # copied in, so the checkout it finds itself in is this one (config.Repo)
                shutil.copy2(REPO / named, program)
        # Trimmed, a build in this piece's own tree finds what others cached (every_file).
        built = subprocess.run(["go", "build", "-o", program, "-trimpath", "./cmd/ak"], env=ENV,
                               cwd=Path(tree, "go"), capture_output=True,
                               text=True) if build and not named else None
        # a checkout, as Go finds the one it runs from (config.Repo), without the history; its
        # files staged, so what reads the checkout's tracked files (akinstall.py) finds them as
        # it does in the checkout Python runs from
        subprocess.run(["git", "init", "-q", tree], check=True)
        subprocess.run(["git", "-C", tree, "add", "-A"], check=True)
        yield tree, program, built


def switch(tree):
    """Shape the copy at `tree` like the commit switching ak to Go: each folder SWITCHED and
    install.sh go/'s, what KEPT names left as it is, and bin/ empty for the program."""
    go = tree / "go"
    shutil.copy2(go / "install.sh", tree)
    shutil.rmtree(tree / "bin", ignore_errors=True)
    (tree / "bin").mkdir()
    for part in SWITCHED:
        for old in (tree / part).glob("*"):
            if f"{part}/{old.name}" not in KEPT:
                shutil.rmtree(old) if old.is_dir() and not old.is_symlink() else old.unlink()
        shutil.copytree(go / part, tree / part, symlinks=True, dirs_exist_ok=True)
        # A link leads where it led in go/, go/bin being bin/ now: tools/ak to the program, and a
        # shim and an adapter's manifest into go/internal, which stays.
        for link in (tree / part / new.name for new in (go / part).iterdir() if new.is_symlink()):
            led = Path(os.path.normpath(go / part / os.readlink(link))).relative_to(go)
            led = (tree if led.parts[0] in (*SWITCHED, "bin") else go) / led
            link.unlink()
            link.symlink_to(os.path.relpath(led, link.parent))


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
        name_failed(sorted(unlisted), "NOT_THERE")
        alone = os.environ.get("AK_GO_ALONE") == "1"
        leans = set() if alone else leaning(REPO)
        # Said first: a claim a milestone adds that leans on Python's files reads why it fails.
        switched = "judged in the switched tree (tests/test_go_keys.py): " + (
            "AK_GO_ALONE=1 judges every claim there\n" if alone else
            "go/leans/ does not name its key file\n")
        failed, took = [], {}
        for lean in (False, True):
            judged = [claim for claim in listed if (claim[0] in leans) == lean]
            if not judged:
                continue
            # A lean's run with the caller's AK_GO_ALONE, which is not 1 where any is one.
            with (patch.dict(os.environ, {} if lean else {"AK_GO_ALONE": "1"}),
                  checkout(build=True) as (tree, program, built)):
                if built and built.returncode:
                    # Go that does not build fails every claim asked of it, never as a skip: the
                    # landing suite counts a skipped case as passed.  Named, a landing's narrowing
                    # finds the change that broke the build: unnamed, the claim proves nothing on
                    # each stack holding that change (land._probe).
                    name_failed([name for name, *_ in listed], "FAILED_PARTS")
                    self.fail(built.stderr)
                # One after another: every_file.py already runs other files beside this one.
                for name, *parts in judged:
                    claim = " ".join((name, *parts))
                    # Named as it starts: a few claims on a loaded host, or all of go/keys.txt, run
                    # longer than a check may stay silent, and a claim that hangs is then the last
                    # line.
                    print(f"--- {claim}", flush=True)
                    began = time.monotonic()
                    done, passed = run(tree, program, name, *parts)
                    if passed:
                        took[name] = time.monotonic() - began
                        name_timed(took)
                    else:
                        failed.append(claim)
                        print(f"{'' if lean else switched}{done.stdout}{done.stderr}", flush=True)
        name_failed([claim.split()[0] for claim in failed], "FAILED_PARTS")
        self.assertFalse(unlisted, "go/keys.txt does not list these")
        self.assertFalse(failed, "these claims of go/keys.txt fail or skip")


if __name__ == "__main__":
    # The claims' names are Claims' own arguments, never unittest's.
    unittest.main(argv=sys.argv[:1], verbosity=2)

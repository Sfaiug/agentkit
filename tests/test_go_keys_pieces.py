"""The Go keys check runs in pieces cut by its claims' measured seconds: no piece nears the
silence that stops a landing, every claim of go/keys.txt runs in exactly one, and more claims
make more pieces, none past its bound.

Offline: the real tests/every_file.py runs a landing's three shares (AK_SHARD) on a temporary
checkout holding the real test_go_keys.py, stand-in keys noting the tree each runs from and a
stand-in `go`; the claims' seconds are kept as the suite keeps its files' (suite_times), first
those a run measures, then made-up ones of minutes.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, record, suite_times

# Notes the claim it runs for and the program Go's claims are judged by, built in the piece's tree.
KEY = '''import os, pathlib, sys, unittest
class Acme(unittest.TestCase):
    def test_it(self):
        if "AK_BIN" in os.environ:
            with open(os.environ["ACME_LOG"], "a") as fh:
                fh.write(" ".join([os.environ["AK_BIN"], pathlib.Path(__file__).stem,
                                   *sys.argv[1:]]) + "\\n")
unittest.main()
'''
# test_go_keys.py builds in test_go.py's environment; the stand-in `go` writes where `-o` says.
TEST_GO = ('import os\nENV = dict(os.environ)\n'
           'if __name__ == "__main__":\n    print("TESTS_RUN=1")\n')
GO = '#!/bin/sh\nmkdir -p "$(dirname "$3")" && echo built >"$3"\n'
SHARES = ("1/3", "2/3", "3/3")


def name(n):
    return f"test_key_acme_{n:02d}"


def minutes(n):
    """The made-up seconds of claim `n`: one to four and a half minutes."""
    return 60 + 6 * n


class GoKeysPieces(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-go-keys-pieces-", dir=REPO)))
        self.root = self.sandbox / "acme"
        (self.root / "tests").mkdir(parents=True)
        (self.root / "go").mkdir()
        (self.root / "tests/smoke.sh").write_text("")
        (self.root / "tests/test_go.py").write_text(TEST_GO)
        for file in ("test_go_keys.py", "suite_shares.py"):
            shutil.copy(REPO / "tests" / file, self.root / "tests")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.sandbox / "bin").mkdir()
        (self.sandbox / "bin/go").write_text(GO)
        (self.sandbox / "bin/go").chmod(0o755)
        self.env = {**{k: v for k, v in os.environ.items()
                       if not k.startswith(("AGENTKIT_", "AK_"))},
                    "PATH": f"{self.sandbox / 'bin'}{os.pathsep}{os.environ['PATH']}",
                    "AK_CGROUP_FILE": str(self.sandbox / "no-cgroup"),
                    "AK_HOST_READINGS": '{"cpu_pressure": 0, "free_mb": 4096}'}
        self.enterContext(patch.object(config, "HOME", self.sandbox / "home/.agentkit"))

    def land(self, count, times=""):
        """The pieces each share of a landing runs for go/keys.txt's `count` claims, handed the
        record `times`: by the tree each ran in, its claims as their lines; and the claims of
        go/keys.txt, one of them claimed twice, as go/keys.txt holds some."""
        claims = [f"{name(n)} Acme" for n in range(count)]
        claims.insert(4, f"{name(3)} Acme.test_it")
        (self.root / "go/keys.txt").write_text("".join(f"{claim}\n" for claim in claims))
        for n in range(count):
            (self.root / "tests" / f"{name(n)}.py").write_text(KEY)
        output, shares = self.sandbox / "suite.log", []
        output.write_text("")
        for share in SHARES:
            ran = self.sandbox / f"ran-{share.replace('/', '-of-')}.log"
            ran.unlink(missing_ok=True)
            with output.open("a") as out:
                done = subprocess.run([sys.executable, REPO / "tests/every_file.py", self.root],
                                      env=dict(self.env, AK_SHARD=share, AK_TIMES=times,
                                               ACME_LOG=str(ran)),
                                      stdin=subprocess.DEVNULL, stdout=out,
                                      stderr=subprocess.STDOUT, timeout=600)
            self.assertEqual(done.returncode, 0, output.read_text())
            pieces = {}
            for line in ran.read_text().splitlines() if ran.exists() else []:
                tree, claim = line.split(" ", 1)
                pieces.setdefault(tree, []).append(claim)
            shares.append(pieces)
        # The suite keeps the times its pieces printed, as the gate does from their output.
        suite_times.keep(self.root, output)
        self.assertCountEqual([claim for pieces in shares for piece in pieces.values()
                               for claim in piece], claims, "a claim runs in no piece or two")
        return shares

    def kept(self, count):
        """The record handed to a suite once a check printed made-up seconds for `count` claims."""
        printed = self.sandbox / "printed.log"
        printed.write_text("".join(suite_times.passed(f"tests/test_go_keys.py::{name(n)}",
                                                      minutes(n)) + "\n" for n in range(count)))
        suite_times.keep(self.root, printed)
        return suite_times.handed(self.root)

    def test_every_claim_runs_in_exactly_one_piece_and_its_seconds_are_kept(self):
        shares = self.land(8)
        twice = [piece for pieces in shares for piece in pieces.values()
                 if f"{name(3)} Acme" in piece]
        self.assertIn(f"{name(3)} Acme.test_it", twice[0], "a key's two claims split")
        kept = suite_times.read(suite_times.handed(self.root))
        self.assertLessEqual({f"tests/test_go_keys.py::{name(n)}" for n in range(8)}, kept.keys())
        # Measured, the claims share pieces: the stand-ins take next to no time.
        self.assertLessEqual(sum(map(len, self.land(8, suite_times.handed(self.root)))), 3)

    def test_no_piece_nears_the_silence_and_more_claims_make_more_pieces(self):
        silence = 60 * record.SILENCE_MINUTES
        self.assertGreater(sum(minutes(n) for n in range(24)), 2 * silence)
        made = []
        for count in (24, 36):
            shares = self.land(count, self.kept(count))
            self.assertTrue(all(shares), "a share runs no piece")
            for pieces in shares:
                for piece in pieces.values():
                    names = {claim.split()[0] for claim in piece}
                    self.assertLessEqual(sum(minutes(int(key[-2:])) for key in names),
                                         silence / 2, piece)
            made.append(sum(map(len, shares)))
        self.assertGreater(made[1], made[0])


if __name__ == "__main__":
    unittest.main()

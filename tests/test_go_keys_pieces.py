"""The Go keys check runs in pieces cut by its claims' measured seconds, kept as the suite keeps a
file's (suite_times): no piece nears the silence that stops a landing, every claim of go/keys.txt
runs in exactly one, and more claims make more pieces, none past its bound but a claim past it,
alone.  Offline: the real every_file.py runs three shares (AK_SHARD) of a checkout of stand-in keys
and a stand-in `go`.
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
sys.path[:0] = [str(REPO), str(REPO / "tests")]
import every_file
from agentkit import config, record, suite_times

# Notes the claim it runs for and the program it judges, built in its piece's own tree.
KEY = '''import os, sys, unittest
class Acme(unittest.TestCase):
    def test_it(self):
        if "AK_BIN" in os.environ:
            with open(os.environ["ACME_LOG"], "a") as fh:
                fh.write(" ".join([os.environ["AK_BIN"], *sys.argv]) + "\\n")
unittest.main()
'''
# test_go_keys.py builds in test_go.py's environment; the stand-in `go` writes where `-o` says.
TEST_GO = ('import os\nENV = dict(os.environ)\n'
           'if __name__ == "__main__":\n    print("TESTS_RUN=1")\n')
GO = '#!/bin/sh\nmkdir -p "$(dirname "$3")" && echo built >"$3"\n'
# Made-up measures: one to four and a half minutes a claim.
SECONDS = {f"test_key_acme_{n:02d}": 60 + 6 * n for n in range(36)}


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
        (self.sandbox / "go").write_text(GO)
        (self.sandbox / "go").chmod(0o755)
        self.enterContext(patch.object(config, "HOME", self.sandbox / "home/.agentkit"))

    def land(self, count, times=""):
        """For go/keys.txt's first `count` claims, handed the record `times`, the pieces each
        share runs: their claims, as `<key> <part>`, by the tree each ran in."""
        claims = [f"{key} Acme" for key in list(SECONDS)[:count]]
        claims.insert(1, "test_key_acme_00 Acme.test_it")   # a key claimed twice, as some are
        (self.root / "go/keys.txt").write_text("".join(f"{claim}\n" for claim in claims))
        for key in list(SECONDS)[:count]:
            (self.root / "tests" / f"{key}.py").write_text(KEY)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        output, shares = self.sandbox / "suite.log", []
        for share in ("1/3", "2/3", "3/3"):
            ran = self.sandbox / f"ran-{share[0]}.log"
            with output.open("a") as out:
                done = subprocess.run(
                    [sys.executable, REPO / "tests/every_file.py", self.root],
                    env=dict(env, AK_SHARD=share, AK_TIMES=times, ACME_LOG=str(ran),
                             PATH=f"{self.sandbox}{os.pathsep}{os.environ['PATH']}",
                             AK_CGROUP_FILE=str(self.sandbox / "no-cgroup"),
                             AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}'),
                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, timeout=600)
            self.assertEqual(done.returncode, 0, output.read_text())
            pieces = {}
            for tree, key, *parts in map(str.split, ran.read_text().splitlines()
                                         if ran.exists() else []):
                pieces.setdefault(tree, []).append(" ".join([Path(key).stem, *parts]))
            ran.unlink(missing_ok=True)
            shares.append(pieces)
        # The suite keeps the times its pieces printed, as the gate does from their output.
        suite_times.keep(self.root, output)
        output.unlink()
        self.assertCountEqual([claim for pieces in shares for piece in pieces.values()
                               for claim in piece], claims, "a claim runs in no piece or two")
        return shares

    def test_every_claim_runs_in_exactly_one_piece_and_its_seconds_are_kept(self):
        shares = self.land(8)
        self.assertTrue(any({"test_key_acme_00 Acme", "test_key_acme_00 Acme.test_it"} <= set(
            piece) for pieces in shares for piece in pieces.values()), "a key's claims split")
        kept = suite_times.read(suite_times.handed(self.root))
        self.assertLessEqual({f"tests/test_go_keys.py::{key}" for key in list(SECONDS)[:8]},
                             kept.keys())
        # Measured, the claims share pieces: the stand-ins take next to no time.
        self.assertLessEqual(sum(map(len, self.land(8, suite_times.handed(self.root)))), 3)

    def test_no_piece_nears_the_silence_and_more_claims_make_more_pieces(self):
        silence = 60 * record.SILENCE_MINUTES
        self.assertGreater(sum(list(SECONDS.values())[:24]), 2 * silence)
        made = []
        for count in (24, 36):
            printed = self.sandbox / "printed.log"
            printed.write_text("".join(f"{suite_times.passed(f'tests/test_go_keys.py::{key}', s)}\n"
                                       for key, s in SECONDS.items()))
            suite_times.keep(self.root, printed)
            shares = self.land(count, suite_times.handed(self.root))
            self.assertTrue(all(shares), "a share runs no piece")
            for piece in (piece for pieces in shares for piece in pieces.values()):
                total = sum(SECONDS[key] for key in {claim.split()[0] for claim in piece})
                self.assertLessEqual(total, silence / 2, piece)
            made.append(sum(map(len, shares)))
        self.assertGreater(made[1], made[0])

    def test_a_claim_past_the_bound_runs_alone_and_the_others_still_share(self):
        claims = {"test_key_acme_slow": every_file.PIECE + 1, "test_key_acme": 10,
                  "test_key_widget": 10}
        cost = {f"tests/test_go_keys.py::{key}": seconds for key, seconds in claims.items()}
        self.assertEqual([parts for _, parts, _ in every_file.runs(self.root, cost)],
                         [["test_key_acme_slow"], ["test_key_acme", "test_key_widget"]])
        # suite_times keeps a claim too short to measure as zero seconds.
        cost = {"tests/test_go_keys.py::test_key_acme_slow": every_file.PIECE + 1,
                "tests/test_go_keys.py::test_key_widget": 0.0}
        self.assertEqual([parts for _, parts, _ in every_file.runs(self.root, cost)],
                         [["test_key_acme_slow"], ["test_key_widget"]])


if __name__ == "__main__":
    unittest.main()

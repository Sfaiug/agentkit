"""A suite's pieces are cut and ordered by the times the lander kept from earlier pieces.

Offline: a temporary checkout and HOME, stand-in test runs with injected times and host readings.
"""

from contextlib import nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
import every_file
import suite_shares
from agentkit import config, gate, land, suite_times

# name: (bytes, seconds it takes); by size test_big.py would fill a piece alone
FILES = {"test_slow.py": (300, 60), "test_mid_a.py": (300, 30), "test_mid_b.py": (300, 30),
         "test_big.py": (5000, 1), "test_new.py": (1000, 0.5)}


class SuitePiecesByMeasuredTime(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-measured-time-", dir=REPO)))
        self.root = self.sandbox / "acme"
        (self.root / "tests").mkdir(parents=True)
        (self.root / "tests/smoke.sh").write_text("#!/bin/bash\n")
        for name in suite_shares.STATIC_CHECKS:
            (self.root / "tests" / f"{name}.py").write_text("")
        for name, (size, _) in FILES.items():
            path = self.root / "tests" / name
            path.write_text('print("TESTS_RUN=1")\n#')
            path.write_text(path.read_text().ljust(size - 1, "x") + "\n")
        self.git = ["git", "-C", str(self.root)]
        subprocess.run([*self.git, "init", "-q"], check=True)
        subprocess.run([*self.git, "add", "."], check=True)
        subprocess.run([*self.git, "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                        "commit", "-qm", "acme"], check=True)
        self.enterContext(patch.object(config, "HOME", self.sandbox / "home/.agentkit"))
        self.enterContext(patch.dict(os.environ, {
            "PATH": os.environ.get("PATH", os.defpath), "PYTHONDONTWRITEBYTECODE": "1"},
            clear=True))

    def piece(self, shard, times=""):
        """The files the piece starts, in order, and what it printed."""
        starts, out = [], io.StringIO()

        def measured(_root, path, _env, **_kw):
            starts.append(path.name)
            return 0, "TESTS_RUN=1\n", FILES[path.name][1]

        # A serial pool shows start order without depending on thread scheduling.
        with patch.dict(os.environ, {"AK_SHARD": shard, "AK_TIMES": times}), \
                patch.object(every_file.host, "host_readings", return_value={
                    "cpu_pressure": 0, "free_mb": 230}), \
                patch.object(every_file, "run_file", side_effect=measured), redirect_stdout(out):
            self.assertEqual(every_file.main(self.root), 0)
        return starts, out.getvalue()

    def land_check(self, scratch, ok, text):
        with patch.object(gate, "gate_turn", return_value=nullcontext()), \
                patch.object(gate, "run_done_when", return_value=(ok, text)):
            land._check(self.sandbox, {}, scratch, ["python3 tests/landing.py"],
                        self.sandbox / "lander-acme.log", lambda _line: None)

    def keep_a_suite(self):
        """A suite cut by size, its two pieces' logs kept by a passing landing check."""
        logs = [self.piece(f"{k}/2")[1] for k in (1, 2)]
        self.land_check(self.root, False, "\n".join(logs))
        self.assertEqual(suite_times.handed(self.root), "", "a red check keeps no times")
        # One piece on the suite helper: its log reaches the lander as the other's does.
        self.land_check(self.root, True, f"--- AK_SHARD=1/2 ---\n{logs[0]}\n"
                        f"--- AK_SHARD=2/2 ---\n{logs[1]}\nPASS  tests/test_gone.py (9.0s)\n")

    def test_times_from_a_finished_pieces_log_survive_a_new_box(self):
        self.keep_a_suite()
        box = self.sandbox / "box"
        subprocess.run([*self.git, "worktree", "add", "-q", "--detach", str(box)], check=True)
        times = suite_times.handed(box)
        self.assertEqual(suite_times.read(times),
                         {f"tests/{name}": seconds for name, (_, seconds) in FILES.items()},
                         "a file the checkout lacks leaves the record")
        self.assertEqual(gate.suite_env(None, times)["AK_TIMES"], times)
        # The helper hands its pieces no environment: they get the same record in the command.
        seen = self.sandbox / "seen"
        subprocess.run(["bash", "-c", gate.PINNED_PIECE.format(
            shlex.quote(times), shlex.quote(f'printf %s "$AK_TIMES" >{seen}'))],
            cwd=box, check=True)
        self.assertEqual(seen.read_text(), times)

    def test_shares_balance_measured_time_and_place_the_unmeasured_by_size(self):
        by_size = [set(self.piece(f"{k}/2")[0]) for k in (1, 2)]
        self.assertEqual(by_size[0], {"test_big.py"})
        self.keep_a_suite()
        record = suite_times.read(suite_times.handed(self.root))
        del record["tests/test_new.py"]
        pieces = [set(self.piece(f"{k}/2", json.dumps(record))[0]) for k in (1, 2)]
        # test_new.py, never measured, costs its 1000 bytes at 121 s per 5900 bytes: 20.5 s.
        self.assertEqual(pieces, [{"test_slow.py", "test_new.py"},
                                  {"test_mid_a.py", "test_mid_b.py", "test_big.py"}])

    def test_a_piece_starts_its_files_longest_first(self):
        self.keep_a_suite()
        times = suite_times.handed(self.root)
        # By size test_big.py would start first.
        self.assertEqual(self.piece("1/2", times)[0], ["test_slow.py", "test_big.py"])
        self.assertEqual(self.piece("2/2", times)[0],
                         ["test_mid_a.py", "test_mid_b.py", "test_new.py"])
        self.assertEqual(self.piece("1/1", times)[0], sorted(
            FILES, key=lambda name: -FILES[name][1]))


if __name__ == "__main__":
    unittest.main()

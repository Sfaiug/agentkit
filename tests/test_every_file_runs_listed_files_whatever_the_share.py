"""tests/every_file.py run alone with AK_ONLY set runs every listed file whatever AK_SHARD says;
without AK_ONLY the shares divide the files.

Offline: the real every_file.py runs on a temporary checkout of stand-ins that note each start
and fail as told; the host readings are injected.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

# Each stand-in notes its start; ACME_FAILS names those that fail.
STAND_IN = '''import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["ACME_LOG"], "a") as fh:
    fh.write(name + "\\n")
print("TESTS_RUN=1")
sys.exit(name in os.environ["ACME_FAILS"].split())
'''
FILES = ("test_acme.py", "test_fix_api.py", "test_widget.py")


class EveryFileRunsListedFilesWhateverTheShare(unittest.TestCase):
    def every_file(self, shard, only=None, fails=""):
        """every_file.py's exit, the stand-ins that started and the files it named as failed."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-listed-share-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        tests = root / "tests"
        tests.mkdir()
        (tests / "smoke.sh").write_text("")
        for name in FILES:
            (tests / name).write_text(STAND_IN)
        log, failed, listed = root / "ran.log", root / "failed-tests", root / "only-tests"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(root), ACME_LOG=str(log), ACME_FAILS=fails, AK_SHARD=shard,
                   AK_FAILED=str(failed), AK_CGROUP_FILE=str(root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        if only is not None:
            listed.write_text("".join(f"tests/{name}\n" for name in only))
            env["AK_ONLY"] = str(listed)
        proc = subprocess.run([sys.executable, str(REPO / "tests/every_file.py"), str(root)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=120)
        read = lambda path: sorted(path.read_text().splitlines()) if path.exists() else []
        return proc, read(log), read(failed)

    def test_a_listed_failing_file_runs_twice_fails_and_is_named_in_every_share(self):
        for shard in ("1/2", "2/2"):
            with self.subTest(shard=shard):
                proc, ran, failed = self.every_file(
                    shard, only=["test_acme.py", "test_fix_api.py"], fails="test_acme.py")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertEqual(ran, ["test_acme.py", "test_acme.py", "test_fix_api.py"])
                self.assertEqual(failed, ["tests/test_acme.py"])

    def test_without_a_list_the_shares_divide_the_files(self):
        shares = [self.every_file(shard) for shard in ("1/2", "2/2")]
        for proc, ran, failed in shares:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(ran)
            self.assertEqual(failed, [])
        self.assertEqual(sorted(shares[0][1] + shares[1][1]), sorted(FILES))


if __name__ == "__main__":
    unittest.main()

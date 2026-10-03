"""The landing parts overlap, with whole outputs and unknown or longest files first.

Offline: measured stand-ins, injected host readings and a temporary HOME.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import every_file


class EveryFileOrder(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-file-order-", dir=REPO)))
        self.root = self.sandbox / "checkout"
        self.home = self.sandbox / "home"
        self.home.mkdir()
        (self.root / "tests").mkdir(parents=True)
        (self.root / "tests/smoke.sh").write_text("#!/bin/bash\n")
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(self.home), "PATH": os.environ.get("PATH", os.defpath),
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "PYTHONDONTWRITEBYTECODE": "1",
        }, clear=True))
        self.times = {"test_acme.py": 2, "test_widget.py": 9, "test_fix_api.py": 5}
        for name in self.times:
            (self.root / "tests" / name).write_text('raise AssertionError("use the stand-in")\n')

    def sweep(self):
        starts = []

        def measured(_root, path, _env, **_kw):
            starts.append(path.name)
            return 0, "TESTS_RUN=1\n", self.times[path.name]

        # A serial pool exposes start order without depending on thread scheduling.
        with patch.object(every_file.host, "host_readings", return_value={
                "cpu_pressure": 0, "free_mb": 230}), \
                patch.object(every_file, "run_file", side_effect=measured), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(every_file.main(self.root), 0)
        return starts

    def test_longest_starts_first_by_the_last_measurement(self):
        self.assertCountEqual(self.sweep(), self.times)
        previous = dict(self.times)
        self.times["test_acme.py"], self.times["test_widget.py"] = 20, 1
        self.assertEqual(self.sweep(), sorted(previous, key=previous.get, reverse=True))
        self.assertEqual(self.sweep(), sorted(self.times, key=self.times.get, reverse=True))

    def test_a_file_without_a_measurement_starts_before_the_longest(self):
        self.sweep()
        self.times["test_new.py"] = 0.1
        (self.root / "tests/test_new.py").write_text('print("TESTS_RUN=1")\n')
        starts = self.sweep()
        self.assertEqual(starts[:2], ["test_new.py", "test_widget.py"])
        self.assertCountEqual(starts, self.times)

    def test_timings_live_outside_the_checkout_and_survive_a_new_checkout(self):
        self.sweep()
        cache = self.home / ".cache/agentkit/test-times" / os.uname().nodename
        self.assertFalse(cache.is_relative_to(self.root))
        self.assertEqual({path.name: float(path.read_text()) for path in cache.iterdir()},
                         self.times)
        other = self.sandbox / "other-checkout"
        self.root.rename(other)
        self.root = other
        self.assertEqual(self.sweep(), sorted(self.times, key=self.times.get, reverse=True))

    def test_an_unwritable_cache_does_not_stop_checks(self):
        (self.home / ".cache").write_text("a file cannot hold the cache directory")
        self.assertCountEqual(self.sweep(), self.times)

    def test_both_parts_overlap_print_whole_outputs_and_keep_failures(self):
        line = next(line.removeprefix("tests: ") for line in (REPO / "AGENTS.md").read_text()
                    .splitlines() if line.startswith("tests: "))
        tools, temp = self.sandbox / "bin", self.sandbox / "tmp"
        tools.mkdir()
        temp.mkdir()
        # Exercise the unchanged wrapper's fallback without touching host namespaces.
        unshare = tools / "unshare"
        unshare.write_text("#!/bin/sh\nexit 1\n")
        unshare.chmod(0o755)
        (self.root / "tests/smoke.sh").write_text('''echo "smoke stdout"
echo "smoke stderr" >&2
touch smoke-started
for ((n=0; n<500; n++)); do
    [[ -f files-started ]] && break
    sleep 0.01
done
[[ -f files-started ]] || exit 99
echo "smoke done"
exit "$ACME_SMOKE"
''')
        (self.root / "tests/every_file.py").write_text('''import os, pathlib, sys, time
print("files stdout", flush=True)
print("files stderr", file=sys.stderr, flush=True)
pathlib.Path("files-started").touch()
deadline = time.monotonic() + 5
while not pathlib.Path("smoke-started").exists():
    assert time.monotonic() < deadline, "smoke never started beside files"
    time.sleep(0.01)
print("files done", flush=True)
sys.exit(int(os.environ["ACME_FILES"]))
''')
        expected = "smoke stdout\nsmoke stderr\nsmoke done\nfiles stdout\nfiles stderr\nfiles done\n"
        for smoke, files in ((0, 0), (3, 0), (0, 7), (3, 7)):
            with self.subTest(smoke=smoke, files=files):
                for name in ("smoke-started", "files-started"):
                    (self.root / name).unlink(missing_ok=True)
                env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", TMPDIR=str(temp),
                           ACME_SMOKE=str(smoke), ACME_FILES=str(files))
                proc = subprocess.run(["bash", "-c", line], cwd=self.root, env=env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, files or smoke, proc.stdout + proc.stderr)
                self.assertEqual(proc.stdout, expected)
                self.assertEqual(proc.stderr, "")
                self.assertEqual(list(temp.iterdir()), [], "suite output buffers leaked")


if __name__ == "__main__":
    unittest.main()

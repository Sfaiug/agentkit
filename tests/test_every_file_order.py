"""The landing parts overlap, with whole outputs.

Offline: stand-in parts, injected host readings and a temporary HOME.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
import suite_shares
from agentkit import worker


class EveryFileOrder(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-file-order-", dir=REPO)))
        self.root = self.sandbox / "checkout"
        self.home = self.sandbox / "home"
        self.home.mkdir()
        (self.root / "tests").mkdir(parents=True)
        (self.root / "tests/smoke.sh").write_text("#!/bin/bash\n")
        for name in ("landing.py", "affected.py", "suite_shares.py"):
            (self.root / "tests" / name).write_text((REPO / "tests" / name).read_text())
        for name in suite_shares.STATIC_CHECKS:
            (self.root / "tests" / f"{name}.py").write_text("")
        (self.root / "tests/gate_contract.py").write_text("")
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(self.home), "PATH": os.environ.get("PATH", os.defpath),
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "PYTHONDONTWRITEBYTECODE": "1",
        }, clear=True))
        self.names = ("test_acme.py", "test_widget.py", "test_fix_api.py")
        for name in self.names:
            (self.root / "tests" / name).write_text('raise AssertionError("use the stand-in")\n')

    def landing_env(self):
        tools, temp = self.sandbox / "bin", self.sandbox / "tmp"
        tools.mkdir()
        temp.mkdir()
        # The line refuses a host without its namespace: stand in for one without touching the
        # host's, running what follows the line's `-` as is.
        unshare = tools / "unshare"
        unshare.write_text('#!/bin/sh\nwhile [ "$1" != - ]; do shift; done\nshift\nexec "$@"\n')
        unshare.chmod(0o755)
        return dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", TMPDIR=str(temp))

    def landing_line(self):
        return next(line.removeprefix("tests: ") for line in (REPO / "AGENTS.md").read_text()
                    .splitlines() if line.startswith("tests: "))

    def test_both_parts_overlap_print_whole_outputs_and_keep_failures(self):
        env = self.landing_env()
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
        (self.root / "tests/gate_contract.py").write_text(
            'import os, sys\nprint("contract done")\nsys.exit(int(os.environ["ACME_CONTRACT"]))\n')
        expected = ("smoke stdout\nsmoke stderr\nsmoke done\nfiles stdout\nfiles stderr\nfiles done\n"
                    "contract done\n")
        for smoke, files, contract in ((0, 0, 0), (3, 0, 0), (0, 7, 0), (3, 7, 0), (0, 0, 5)):
            with self.subTest(smoke=smoke, files=files, contract=contract):
                for name in ("smoke-started", "files-started"):
                    (self.root / name).unlink(missing_ok=True)
                env.update(ACME_SMOKE=str(smoke), ACME_FILES=str(files), ACME_CONTRACT=str(contract))
                proc = subprocess.run(["bash", "-c", self.landing_line()], cwd=self.root, env=env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, files or smoke or contract, proc.stdout + proc.stderr)
                self.assertEqual(proc.stdout, expected)
                self.assertEqual(proc.stderr, "")
                self.assertEqual(list(Path(env["TMPDIR"]).iterdir()), [], "suite output buffers leaked")

    def flaky_piece(self):
        # The real runner with what landing.py passes it, always on this checkout: left to
        # its default it would sweep the repository's own tests.
        (self.root / "tests/every_file.py").write_text(
            'import os, sys\nos.execv(sys.executable, [sys.executable, '
            f'{str(REPO / "tests/every_file.py")!r}, os.getcwd(), *sys.argv[2:]])\n')
        for name in self.names:
            (self.root / "tests" / name).write_text('print("TESTS_RUN=1")\n')
        (self.root / "tests/test_acme.py").write_text('''import pathlib, sys
if not pathlib.Path("failed-once").exists():
    pathlib.Path("failed-once").touch()
    sys.exit("acme first run")
if not pathlib.Path("smoke-ended").exists():
    sys.exit("re-ran beside smoke.sh")
print("TESTS_RUN=1")
''')
        return dict(self.landing_env(), AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')

    def test_a_failed_files_re_run_waits_for_smoke_to_end(self):
        env = self.flaky_piece()
        (self.root / "tests/smoke.sh").write_text('''for ((n=0; n<500; n++)); do
    [[ -f failed-once ]] && break
    sleep 0.01
done
sleep 1
touch smoke-ended
''')
        proc = subprocess.run(["bash", "-c", self.landing_line()], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("flaky: tests/test_acme.py failed, then passed on its re-run\n",
                      proc.stdout)

    def test_a_smoke_launch_error_ends_a_piece_whose_failed_file_waits(self):
        # No bash to start smoke.sh with: the error must not leave the re-run waiting on it.
        proc = subprocess.run([sys.executable, "tests/landing.py"], cwd=self.root,
                              env=dict(self.flaky_piece(), PATH=str(self.sandbox / "bin")),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("FileNotFoundError", proc.stderr)

    def test_progress_reaches_the_watchdog_before_either_part_finishes(self):
        (self.root / "tests/smoke.sh").write_text(
            'for n in {0..9}; do echo "smoke $n"; sleep 0.5; done\n')
        (self.root / "tests/every_file.py").write_text(
            'import time\nfor n in range(20):\n'
            '    print(f"files {n}", flush=True); time.sleep(0.5)\n')
        # The contract outlasts smoke.sh without a word: the files' progress streams meanwhile.
        (self.root / "tests/gate_contract.py").write_text("import time\ntime.sleep(9)\n")
        log = self.sandbox / "gate.log"
        # Both phases exceed the real watchdog's window; progress must stream in each.
        with log.open("wb") as output:
            code, _, killed = worker.limited(
                ["bash", "-c", self.landing_line()], 30, silence=3,
                activity=log, output=output, cwd=self.root, env=self.landing_env(),
                stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.assertFalse(killed, log.read_text())
        self.assertEqual(code, 0, log.read_text())
        self.assertEqual(log.read_text().splitlines(),
                         [f"smoke {n}" for n in range(10)] + [f"files {n}" for n in range(20)])


if __name__ == "__main__":
    unittest.main()

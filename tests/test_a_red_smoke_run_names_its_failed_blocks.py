"""A red smoke.sh run names each block a check failed in, once, as `tests/smoke.sh#<block>`;
where it ends red with no block named, each block AK_ONLY lists that started, with none listed
each block of its share, or else itself whole.

Offline: the real tests/landing.py, every_file.py, suite_shares.py and acceptance.sh run on a
temporary checkout whose smoke.sh is a shared setup and three blocks that each note their start
and fail as told, or two of smoke.sh's own offline blocks; the host readings are injected.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from suite_shares import SETUP, STATIC_CHECKS, smoke_blocks

# Like smoke.sh: suite_shares.py chooses the blocks, acceptance.sh counts and names what fails.
ENTRY = '''set -uo pipefail
if [ $# = 0 ]; then
  SMOKE_BODY=$(python3 tests/suite_shares.py tests/smoke.sh) || exit $?
  eval "$SMOKE_BODY"
  exit $?
fi
''' + SETUP + "WORK=$HOME; . tests/acceptance.sh\n"
# A check notes its start and fails where ACME_FAILS names it; beta checks twice.
SMOKE = ENTRY + '''\
check() {
  echo "$1" >>"$ACME_LOG"
  case " $ACME_FAILS " in *" $1 "*) no "$1" ;; *) ok "$1" ;; esac
}
check setup
[ -z "${ACME_EXIT:-}" ] || exit "$ACME_EXIT"
# --- alpha: a suite sourced inside a block is one of its own, as check 5d's
check alpha
( . tests/acceptance.sh; no "a notification was aimed at the configured webhook" )
# --- beta: the fix-api screen
check beta
check beta
# --- gamma: the widget screen
check gamma
# --- shared result
[ -z "${ACME_LATE_EXIT:-}" ] || exit "$ACME_LATE_EXIT"
finish
'''
# smoke.sh's own offline blocks run queue and provider meters, the run queue's check failing.
OFFLINE = (ENTRY + "slot_queue_check() { return 1; }\nusage_fresh_check() { :; }\n"
           + "".join(body for name, body in smoke_blocks((REPO / "tests/smoke.sh").read_text())
                     if name in ("offline_slots", "offline_usage"))
           + "# --- shared offline result\nfinish\n")


class ARedSmokeRunNamesItsFailedBlocks(unittest.TestCase):
    def landing(self, fails="", only=None, smoke=SMOKE, **extra):
        """landing.py's exit, the checks that started, and the tests it named as failed and as
        run; `extra` is the environment's besides."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-smoke-blocks-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        tests = root / "tests"
        tests.mkdir()
        for name in ("landing.py", "suite_shares.py", "acceptance.sh"):
            (tests / name).write_text((REPO / "tests" / name).read_text())
        # The real runner, on this checkout: left to its default it would sweep the repository.
        (tests / "every_file.py").write_text(
            'import os, sys\nos.execv(sys.executable, [sys.executable, '
            f'{str(REPO / "tests/every_file.py")!r}, os.getcwd(), *sys.argv[2:]])\n')
        for name in (*STATIC_CHECKS, "gate_contract"):
            (tests / f"{name}.py").write_text("")
        (tests / "smoke.sh").write_text(smoke)
        files = {name: root / name for name in ("log", "failed", "ran", "only")}
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(root), ACME_LOG=str(files["log"]), ACME_FAILS=fails,
                   AK_FAILED=str(files["failed"]), AK_RAN=str(files["ran"]), AK_SHARD="1/1",
                   AK_CGROUP_FILE=str(root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        env.update(extra)
        if only is not None:
            files["only"].write_text("".join(f"{test}\n" for test in only))
            env["AK_ONLY"] = str(files["only"])
        proc = subprocess.run([sys.executable, "tests/landing.py"], cwd=root, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=120)
        read = lambda path: path.read_text().splitlines() if path.exists() else []
        return proc, read(files["log"]), read(files["failed"]), read(files["ran"])

    def test_a_failed_check_names_its_block_once(self):
        proc, log, failed, _ = self.landing(fails="beta")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(log, ["setup", "alpha", "beta", "beta", "gamma"])
        self.assertEqual(failed, ["tests/smoke.sh#beta"])

    def test_the_named_block_runs_alone_and_is_named_again(self):
        proc, log, failed, ran = self.landing(fails="beta", only=["tests/smoke.sh#beta"])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(log, ["setup", "beta", "beta"])
        self.assertEqual((failed, ran), (["tests/smoke.sh#beta"], ["tests/smoke.sh#beta"]))

    def test_of_the_listed_blocks_only_the_failed_one_is_named(self):
        proc, log, failed, ran = self.landing(
            fails="beta", only=["tests/smoke.sh#alpha", "tests/smoke.sh#beta"])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(log, ["setup", "alpha", "beta", "beta"])
        self.assertEqual(ran, ["tests/smoke.sh#alpha", "tests/smoke.sh#beta"])
        self.assertEqual(failed, ["tests/smoke.sh#beta"])

    def test_a_red_in_no_block_names_smoke_sh_whole(self):
        # A fourth share of three blocks owns none; a listed block that never started is no name.
        for fails, only, extra in (("setup", None, {"AK_SHARD": "4/4"}),
                                   ("", None, {"AK_SHARD": "4/4", "ACME_EXIT": "3"}),
                                   ("", ["tests/smoke.sh#alpha"], {"ACME_EXIT": "3"})):
            with self.subTest(fails=fails, only=only, **extra):
                proc, _, failed, _ = self.landing(fails=fails, only=only, **extra)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(failed, ["tests/smoke.sh"])

    def test_a_red_before_any_block_names_the_shares_blocks(self):
        # Two shares split the three blocks: the first owns those its green run starts.
        _, owned, _, _ = self.landing(AK_SHARD="1/2")
        share = [f"tests/smoke.sh#{name}" for name in owned[1:]]
        proc, log, failed, _ = self.landing(AK_SHARD="1/2", ACME_EXIT="3")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual((log, failed), (["setup"], share))
        proc, log, _, ran = self.landing(only=share)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((log, ran), (owned, share))

    def test_a_red_no_check_named_names_each_listed_block_that_started(self):
        listed = ["tests/smoke.sh#alpha", "tests/smoke.sh#gamma"]
        # gate.run_suite's re-run of a red piece's named tests asks for no AK_RAN.
        for asked in ({}, {"AK_RAN": ""}):
            with self.subTest(**asked):
                proc, log, failed, ran = self.landing(only=listed, ACME_LATE_EXIT="3", **asked)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertEqual((log, failed), (["setup", "alpha", "gamma"], listed))
                self.assertEqual(ran, [] if asked else listed)

    def test_an_offline_check_names_its_block(self):
        ids = ["tests/smoke.sh#offline_slots", "tests/smoke.sh#offline_usage"]
        for only in (None, ids):
            with self.subTest(only=only):
                proc, _, failed, _ = self.landing(only=only, smoke=OFFLINE,
                                                  AGENTKIT_SMOKE_OFFLINE="1")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertEqual(failed, ids[:1])


if __name__ == "__main__":
    unittest.main()

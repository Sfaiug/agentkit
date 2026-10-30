"""agentkit's suite runs only what a change can affect when AK_CHANGED names its files.

Offline: the real tests/landing.py, every_file.py, suite_shares.py and affected.py run on a
temporary checkout of stand-in test files and a stand-in smoke.sh, its change one commit over
its base; the host readings are injected.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from affected import selection
from agentkit import gate
from suite_shares import SETUP, STATIC_CHECKS

# Each stand-in notes its start, and fails when ACME_FAILS names it.
STAND_IN = '''import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["ACME_LOG"], "a") as fh:
    fh.write(name + "\\n")
print("TESTS_RUN=1")
sys.exit(name in os.environ["ACME_FAILS"].split())
'''
# Like smoke.sh: suite_shares.py chooses the blocks, acceptance.sh's NFAIL counts failed checks,
# the offline guard's OFFLINE_RC its own, and a shared helper's argument picks the file it runs.
SMOKE = f'''if [ $# = 0 ]; then
  SMOKE_BODY=$(python3 tests/suite_shares.py tests/smoke.sh) || exit $?
  eval "$SMOKE_BODY"
  exit $?
fi
{SETUP}NFAIL=0
check() {{
  echo "smoke.sh#$1" >>"$ACME_LOG"
  case " $ACME_FAILS " in *" smoke.sh#$1 "*) return 1 ;; esac
}}
lifecycle_check() {{ python3 "tests/test_$1.py"; }}
if [ "${{AGENTKIT_SMOKE_OFFLINE:-0}}" = 1 ]; then
  OFFLINE_RC=0
# --- offline_fees: the fees screen
  check offline_fees || OFFLINE_RC=1
# --- offline_refunds: refunds keep their fees
  check offline_refunds || OFFLINE_RC=1
# --- offline_other: other
  check offline_other || OFFLINE_RC=1
# --- shared offline result ---
  exit "$OFFLINE_RC"
fi
# --- 7: makes what 7b reads (suite_shares.DEPENDENCIES)
check 7 || NFAIL=$((NFAIL + 1))
# --- 7b: invoices
check 7b && python3 tests/test_invoice.py || NFAIL=$((NFAIL + 1))
# --- acme: the paybook screen
check acme && lifecycle_check receipt || NFAIL=$((NFAIL + 1))
# --- fix_api: other
check fix_api || NFAIL=$((NFAIL + 1))
# --- shared result ---
case " $ACME_FAILS " in *" a-strict-skip "*) exit 1 ;; esac
[ "$NFAIL" = 0 ]
'''
BASE = {
    "paybook.py": "def total(n):\n    return n * 2\n",
    "tests/smoke.sh": SMOKE,
    **{f"tests/{name}.py": STAND_IN for name in (*STATIC_CHECKS, "gate_contract")},
    "tests/test_paybook.py": STAND_IN,
    "tests/test_receipt.py": STAND_IN + "# adds up to its total\n",
    "tests/test_invoice.py": STAND_IN + "# the invoice's total\n",
    "tests/test_unrelated.py": STAND_IN,
    **{f"tests/{name}.py": (REPO / "tests" / f"{name}.py").read_text()
       for name in ("landing", "every_file", "suite_shares", "affected")},
    # every_file.py imports agentkit: this checkout's package holds the real one's modules.
    "agentkit/__init__.py": f"__path__.append({str(REPO / 'agentkit')!r})\n",
}
CHANGE = {"paybook.py": "def total(n):\n    return n * 3\n"}
STATIC = [f"tests/{name}.py" for name in STATIC_CHECKS]


class SuiteNarrowsToAChange(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-narrow-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        git = lambda *args: subprocess.run(
            ["git", "-c", "user.name=acme", "-c", "user.email=acme@example.invalid",
             "-c", "commit.gpgsign=false", *args], cwd=self.root, check=True, capture_output=True)
        git("init", "-q")
        for files in (BASE, CHANGE):
            for path, text in files.items():
                (self.root / path).parent.mkdir(parents=True, exist_ok=True)
                (self.root / path).write_text(text)
            git("add", "-A")
            git("commit", "-q", "-m", "change")

    def pieces(self, total, changed=None, only=None, fails="", **extra):
        """Each piece's exit, the tests it named as run and as failed, and what started in it;
        `extra` is the environment's besides."""
        found = []
        for number in range(1, total + 1):
            files = {name: self.root / f"{name}-{number}" for name in ("ran", "failed", "log")}
            for path in files.values():
                path.unlink(missing_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
            env.update(HOME=str(self.root), ACME_LOG=str(files["log"]),
                       ACME_FAILS=fails, AK_SHARD=f"{number}/{total}",
                       AK_RAN=str(files["ran"]), AK_FAILED=str(files["failed"]),
                       AK_CGROUP_FILE=str(self.root / "no-cgroup"),
                       AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
            env.update(extra)
            for name, tests in (("AK_CHANGED", changed), ("AK_ONLY", only)):
                if tests is not None:
                    (self.root / name).write_text("".join(f"{test}\n" for test in tests))
                    env[name] = str(self.root / name)
            proc = subprocess.run([sys.executable, "tests/landing.py"], cwd=self.root, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=120)
            read = lambda path: path.read_text().splitlines() if path.exists() else []
            found.append((proc.returncode, read(files["ran"]), read(files["failed"]),
                          sorted(read(files["log"]))))
            self.assertIn(proc.returncode, (0, 1), proc.stdout + proc.stderr)
        return found

    def test_the_pieces_run_the_change_s_selection_each_test_once(self):
        chosen = selection(self.root, list(CHANGE), "HEAD^")
        self.assertEqual(sorted(chosen), sorted([
            *STATIC, "tests/smoke.sh#7b", "tests/smoke.sh#acme", "tests/test_invoice.py",
            "tests/test_paybook.py", "tests/test_receipt.py"]))
        # 7 is named too, as it runs beside the 7b that depends on it.
        wanted = [*chosen, "tests/every_file.py", "tests/smoke.sh#7"]
        for total in (1, 3):
            with self.subTest(total=total):
                pieces = self.pieces(total, changed=list(CHANGE))
                self.assertEqual([code for code, *_ in pieces], [0] * total)
                self.assertEqual(sorted(test for _, ran, *_ in pieces for test in ran),
                                 sorted(wanted))
                self.assertTrue(all(ran for _, ran, *_ in pieces))
                for _, ran, *_ in pieces:
                    self.assertEqual("tests/smoke.sh#7" in ran, "tests/smoke.sh#7b" in ran)
                # Each file a block also runs starts twice: there and in every_file.py.
                self.assertEqual(sorted(name for *_, log in pieces for name in log), sorted(
                    [f"{name}.py" for name in STATIC_CHECKS] + ["smoke.sh#7", "smoke.sh#7b",
                     "smoke.sh#acme", "test_paybook.py"]
                    + ["test_invoice.py", "test_receipt.py"] * 2))

    def test_unset_or_a_change_to_the_machinery_runs_each_piece_as_today(self):
        for total in (1, 3):
            with self.subTest(total=total):
                today = self.pieces(total)
                self.assertEqual(self.pieces(total, changed=["tests/affected.py"]), today)
                self.assertEqual(self.pieces(total, changed=[]), today)
                self.assertTrue({"test_unrelated.py", "smoke.sh#fix_api", "gate_contract.py"}
                                <= {name for *_, log in today for name in log})

    def test_a_set_ak_only_wins_and_its_blocks_run_with_those_they_depend_on(self):
        [(code, ran, failed, log)] = self.pieces(
            1, changed=list(CHANGE), only=["tests/smoke.sh#7b", "tests/test_unrelated.py"])
        self.assertEqual((code, failed), (0, []))
        self.assertEqual(sorted(ran), ["tests/smoke.sh#7", "tests/smoke.sh#7b",
                                       "tests/test_unrelated.py"])
        self.assertEqual(log, ["smoke.sh#7", "smoke.sh#7b", "test_invoice.py",
                               "test_unrelated.py"])

    def test_a_bad_import_fails_as_the_import_check(self):
        imports = "tests/every_file.py"
        (self.root / "tests/acme_client.py").write_text("import acme_vendored\n")
        [(code, _, failed, _)] = self.pieces(1, changed=list(CHANGE))
        self.assertEqual((code, failed), (1, [imports]))
        [(_, ran, failed, _)] = self.pieces(1)    # a whole run names the import check too
        self.assertIn(imports, set(ran) & set(failed))
        [result] = self.pieces(1, only=[imports])    # as ak re-runs it alone
        self.assertEqual(result, (1, [imports], [imports], []))

    def test_a_red_smoke_sh_names_every_block_it_ran_by_its_exit_alone(self):
        plain = ["tests/smoke.sh#7", "tests/smoke.sh#7b", "tests/smoke.sh#acme"]
        offline = ["tests/smoke.sh#offline_fees", "tests/smoke.sh#offline_refunds"]
        for fails, changed, blocks, mode in (
                ("smoke.sh#acme", list(CHANGE), plain, {}),
                ("a-strict-skip", list(CHANGE), plain, {}),
                ("smoke.sh#offline_fees", ["fees.py"], offline, {"AGENTKIT_SMOKE_OFFLINE": "1"})):
            with self.subTest(fails=fails):
                # ak's first go asks for no AK_RAN: only a run of AK_ONLY's tests does.
                [(code, _, failed, _)] = self.pieces(1, changed=changed, fails=fails, AK_RAN="",
                                                     **mode)
                self.assertEqual((code, sorted(failed)), (1, blocks))
                [(code, ran, failed, _)] = self.pieces(1, only=blocks, fails=fails, **mode)
                self.assertEqual((code, sorted(ran), sorted(failed)), (1, blocks, blocks))

    def test_agentkit_s_own_suite_opts_its_rounds_in(self):
        line = next(line for line in (REPO / "AGENTS.md").read_text().splitlines()
                    if line.startswith("tests: "))
        self.assertTrue(gate.names_changed(line))


if __name__ == "__main__":
    unittest.main()

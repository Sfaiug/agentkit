"""Suite pieces share the safety guard, cover other checks/files once and isolate writes.

Executed suites are tiny stand-ins in temporary checkouts, using the real entry, setup
and tmux guard. No landing suite, live process, login or state is touched.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import every_file
import suite_shares as suite

SMOKE = (REPO / "tests/smoke.sh").read_text()
BLOCKS = suite.smoke_blocks(SMOKE)


class SuiteShares(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-shares-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("AK_", "AGENTKIT_"))}
        self.env.update(HOME=str(self.root),
                        AK_HOST_READINGS='{"cpus": 2, "load": 0, "cpu_pressure": 12, "free_mb": 4096}',
                        AK_CGROUP_FILE=str(self.root / "no-cgroup"))

    def test_piece_is_one_based_and_unset_or_one_of_one_means_all(self):
        for value, wanted in (("", (1, 1)), ("1/1", (1, 1)), ("2/3", (2, 3))):
            self.assertEqual(suite.shard(value), wanted)
        for value in ("1", "0/3", "4/3", "1/0", "-1/3", "01/3", "1/x", "1/3\n"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "AK_SHARD"):
                suite.shard(value)
        self.assertEqual(suite.smoke_source(SMOKE, REPO, (1, 1)),
                         SMOKE[SMOKE.index(suite.SETUP):])

    def test_every_real_block_has_exactly_one_owner_and_keeps_its_body(self):
        names = [name for name, _ in BLOCKS if name is not None]
        self.assertEqual(len(names), len(set(names)), "duplicate smoke check header")
        for total in (1, 2, 3, 7, len(names) + 1):
            owners = suite.smoke_owners(BLOCKS, REPO, total)
            seen = []
            for number in range(1, total + 1):
                chosen = suite.smoke_source(SMOKE, REPO, (number, total))
                for name, body in BLOCKS:
                    if name is None or owners[name] == number:
                        self.assertIn(body, chosen)
                        if name is not None:
                            seen.append(name)
                    else:
                        self.assertNotIn(body, chosen)
            self.assertCountEqual(seen, names)

    def test_dependent_checks_and_background_launches_stay_together(self):
        for total in (2, 3, 7):
            for live, offline in ((False, False), (True, False), (False, True)):
                owners = suite.smoke_owners(BLOCKS, REPO, total, live, offline)
                for group in suite.DEPENDENCIES:
                    self.assertEqual(len({owners[name] for name in group}), 1, group)
                for number in range(1, total + 1):
                    chosen = suite.smoke_source(SMOKE, REPO, (number, total), live, offline)
                    proc = subprocess.run(["bash", "-n"], input=chosen,
                                          capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_tmux_guard_stops_every_piece_before_an_unsafe_check(self):
        guard = next(body for _, body in BLOCKS if body.startswith("# --- 0:"))
        stub = suite.SETUP + '''
WORK="$HOME/work"
export TMUX_TMPDIR="$WORK/tmux"
export AGENTKIT_TMUX_SOCKET=agentkit-test
ok() { :; }
no() { :; }
finish() { :; }
tmux() { echo reached-tmux; }
''' + guard
        for name in ("acme", "fix_api", "widget"):
            stub += f"# --- {name}: fixture\ntmux -L agentkit-test kill-session -t acme\n"
        for number in (1, 2, 3):
            self.assertIn(guard, suite.smoke_source(SMOKE, REPO, (number, 3)))
        for damage in ("", "smoke.sh", "live.sh", "e2e-fresh.sh",
                       "TMUX_TMPDIR", "AGENTKIT_TMUX_SOCKET"):
            source = stub
            if damage == "smoke.sh":
                source = source.replace("tmux -L agentkit-test kill-session", "tmux kill-session")
            elif damage in ("TMUX_TMPDIR", "AGENTKIT_TMUX_SOCKET"):
                source = source.replace(f"\nexport {damage}=", f"\n{damage}=")
            (self.root / "tests/smoke.sh").write_text(source)
            for filename in ("live.sh", "e2e-fresh.sh"):
                (self.root / "tests" / filename).write_text(
                    "tmux kill-server\n" if damage == filename else "")
            for number in (1, 2, 3):
                with self.subTest(damage=damage, number=number):
                    chosen = suite.smoke_source(source, self.root, (number, 3))
                    proc = subprocess.run(["bash"], input=chosen,
                                          env=dict(self.env, REPO=str(self.root)),
                                          capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 1 if damage else 0,
                                     proc.stdout + proc.stderr)
                    if damage:
                        self.assertIn("nothing else in this file may run", proc.stdout)
                        self.assertNotIn("reached-tmux", proc.stdout)
                    else:
                        self.assertIn("reached-tmux", proc.stdout)

    def test_heavy_work_is_spread_and_selection_is_stable(self):
        costs = {str(n): n for n in range(1, 50)}
        owners = suite.shares(costs, 3)
        loads = [sum(cost for name, cost in costs.items() if owners[name] == piece)
                 for piece in (1, 2, 3)]
        self.assertLessEqual(max(loads) - min(loads), 1)
        self.assertEqual(owners, suite.shares(dict(reversed(list(costs.items()))), 3))
        self.assertEqual(suite.shares({}, 3), {})
        self.assertEqual(suite.shares({"acme": 1}, 1000000000), {"acme": 1})

    def test_retry_clock_does_not_reserve_a_piece_for_backoff(self):
        # The retry fakes advance a clock, so their old 360s wait is no longer work.
        retry = [(name, body) for name, body in BLOCKS if name in ("retry_start", "9")]
        others = [(name, ":\n" * 100) for name in ("acme", "fix_api", "widget")]
        owners = suite.smoke_owners(retry + others, self.root, 3)
        self.assertEqual(owners["retry_start"], owners["9"])
        self.assertIn(owners["9"], {owners[name] for name, _ in others})

    def test_smoke_entry_runs_only_its_piece_with_private_setup(self):
        # Exercise the real entry and sandbox setup, replacing all expensive checks.
        setup_end = SMOKE.index('export PATH="$REPO/bin:$PATH"')
        stub = SMOKE[:setup_end] + '''
printf 'sandbox: %s|%s|%s\n' "$HOME" "$TMPDIR" "$PYTHONPYCACHEPREFIX"
mark() { printf 'ran: %s\n' "$1"; }
'''
        for name in ("retry_start", "9", "7", "7b", "16", "33", "20", "20e", "35",
                     "acme", "fix_api", "widget"):
            stub += f"# --- {name}: fixture\n"
            if name == "7":
                stub += 'printf fixture >"$HOME/install-fixture"\n'
            elif name == "7b":
                stub += '[ -f "$HOME/install-fixture" ] || exit 1\n'
            stub += f"mark {name}\n"
        stub += "# --- shared result\n"
        script = self.root / "tests/smoke.sh"
        script.write_text(stub)
        (self.root / "tests/suite_shares.py").write_text(
            (REPO / "tests/suite_shares.py").read_text())
        procs = [subprocess.Popen(["bash", str(script)], env=dict(self.env, AK_SHARD=f"{k}/3"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for k in (1, 2, 3)]
        seen, homes = [], []
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, out + err)
            sandbox = next(line for line in out.splitlines() if line.startswith("sandbox: "))
            home, temp, cache = sandbox.removeprefix("sandbox: ").split("|")
            homes.append(home)
            # The boxes a piece's checks start see its HOME in the checkout, not in /tmp, which
            # is each box's own; tmux follows $WORK/tmux to the short temporary directory.
            self.assertEqual(Path(home).parent, self.root)
            self.assertEqual(cache, home + "/pycache")
            socket = Path(temp, f"tmux-{os.getuid()}/agentkit-test")
            self.assertLessEqual(len(os.fsencode(socket)), 103)
            self.assertFalse(Path(home).exists(), "piece left its sandbox behind")
            self.assertFalse(Path(temp).exists(), "piece left its temporary files behind")
            seen.extend(line.removeprefix("ran: ") for line in out.splitlines()
                        if line.startswith("ran: "))
        self.assertEqual(len(set(homes)), 3)
        self.assertCountEqual(seen, [name for name, _ in suite.smoke_blocks(stub)
                                    if name is not None])

    def files(self):
        # HOME, temp and bytecode writes would collide if runners inherited them.
        body = '''import json, os, pathlib, py_compile
name = pathlib.Path(__file__).stem
home = pathlib.Path.home()
(home / "acme-state").write_text(name)
py_compile.compile(__file__, doraise=True)
assert (home / "acme-state").read_text() == name
assert not any(k.startswith(("AK_", "AGENTKIT_")) for k in os.environ)
print("fixture: " + json.dumps({"name": name, "home": str(home),
      "temp": os.environ["TMPDIR"], "cache": os.environ["PYTHONPYCACHEPREFIX"]}))
print("TESTS_RUN=1")
'''
        for n in range(12):
            (self.root / "tests" / f"test_acme_{n:02d}.py").write_text(body + "# padding\n" * n)
        (self.root / "tests/test_smoked.py").write_text('raise SystemExit("ran twice")\n')
        (self.root / "tests/smoke.sh").write_text(
            '# --- 1: already covered in a different piece\n'
            'python3 "$REPO/tests/test_smoked.py"\n')

    def run_files(self, value):
        # main uses the real selection and pool, with a recorder that exposes child output.
        code = '''import sys
sys.path.insert(0, sys.argv[1])
import every_file
run = every_file.run_file
def record(*args):
    result = run(*args)
    print(result[1], end="", flush=True)
    return result
every_file.run_file = record
sys.exit(every_file.main(every_file.Path(sys.argv[2])))
'''
        return subprocess.run([sys.executable, "-c", code, str(REPO / "tests"), str(self.root)],
                              env=dict(self.env, AK_SHARD=value), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def test_files_cover_the_rest_once_with_clean_separate_sandboxes(self):
        self.files()
        with ThreadPoolExecutor(3) as pool:
            procs = list(pool.map(self.run_files, ("1/3", "2/3", "3/3")))
        found, caches = [], set()
        for proc in procs:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            rows = [json.loads(line.removeprefix("fixture: "))
                    for line in proc.stdout.splitlines() if line.startswith("fixture: ")]
            # A piece's files share one bytecode cache that no other piece uses.
            self.assertEqual(len({row["cache"] for row in rows}), 1)
            caches.add(rows[0]["cache"])
            found.extend(rows)
        self.assertEqual(len(caches), 3)
        self.assertCountEqual([row["name"] for row in found],
                              [f"test_acme_{n:02d}" for n in range(12)])
        self.assertEqual(len({row["home"] for row in found}), 12)
        for row in found:
            self.assertEqual(row["home"], row["temp"])
            self.assertFalse(row["cache"].startswith(row["home"]))
            self.assertFalse(Path(row["cache"]).exists())
            socket = Path(row["temp"]) / "acme-fixture-12345678" / f"tmux-{os.getuid()}/agentkit-test"
            self.assertLessEqual(len(os.fsencode(socket.resolve())), 103)
            self.assertFalse(Path(row["home"]).exists())
        self.assertFalse((self.root / "tests/__pycache__").exists())
        for value in ("", "1/1"):
            proc = self.run_files(value)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(proc.stdout.count("fixture: "), 12)

    def test_invalid_piece_fails_before_starting_checks(self):
        self.files()
        for value in ("0/3", "4/3", "1/0", "acme"):
            proc = self.run_files(value)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("AK_SHARD", proc.stderr)
            self.assertNotIn("fixture: ", proc.stdout)
        # Only the entry is executed; an invalid shard must fail before sandbox setup.
        script = self.root / "tests/smoke.sh"
        script.write_text(SMOKE[:SMOKE.index(suite.SETUP)] + suite.SETUP + "exit 97\n")
        (self.root / "tests/suite_shares.py").write_text(
            (REPO / "tests/suite_shares.py").read_text())
        proc = subprocess.run(["bash", str(script)], env=dict(self.env, AK_SHARD="4/3"),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("AK_SHARD", proc.stderr)

    def test_a_failing_check_or_file_fails_exactly_its_piece(self):
        script = self.root / "tests/smoke.sh"
        script.write_text(SMOKE[:SMOKE.index(suite.SETUP)] + suite.SETUP +
                          'FAILED=0\n# --- broken: fixture\nFAILED=1\n'
                          '# --- passing: fixture\n:\n'
                          '# --- shared result\nexit "$FAILED"\n')
        (self.root / "tests/suite_shares.py").write_text(
            (REPO / "tests/suite_shares.py").read_text())
        codes = [subprocess.run(["bash", str(script)], env=dict(self.env, AK_SHARD=f"{k}/3"),
                                capture_output=True, timeout=30).returncode for k in (1, 2, 3)]
        self.assertEqual(sorted(codes), [0, 0, 1])
        (self.root / "tests/test_broken.py").write_text('raise SystemExit("acme failure")\n')
        (self.root / "tests/test_passing.py").write_text('print("TESTS_RUN=1")\n')
        procs = [self.run_files(f"{k}/3") for k in (1, 2, 3)]
        self.assertEqual(sorted(proc.returncode for proc in procs), [0, 0, 1])
        failed = next(proc for proc in procs if proc.returncode)
        self.assertIn("FAIL  tests/test_broken.py", failed.stdout)

    def test_import_check_does_not_reach_other_pieces_fixtures(self):
        other = self.root / ".ak-test-other-piece"
        other.mkdir()
        (other / "third_party_acme.py").write_text("invalid Python being written (")
        path = self.root / "tests/test_acme.py"
        path.write_text("import third_party_acme\n")
        errors = every_file.import_errors(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("import third_party_acme is outside", errors[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)

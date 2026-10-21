"""The landing suite reaches nothing outside the host; tests/live.sh runs the checks that need it.

Neither suite runs here.  smoke.sh is read, each mode's checks chosen as tests/suite_shares.py
chooses them; tests/live.sh and the AGENTS.md `tests:` line run against stand-in suites, and the
namespace they ask for against a stand-in `unshare`, `ip` and `setpriv`.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import suite_shares
from agentkit import gitcall, run

SMOKE = (REPO / "tests/smoke.sh").read_text()


def tool(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class LandingSuiteOffline(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-landing-offline-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        for name in ("landing.py", "suite_shares.py"):
            (self.root / "tests" / name).write_text((REPO / "tests" / name).read_text())
        for name in suite_shares.STATIC_CHECKS:
            (self.root / "tests" / f"{name}.py").write_text("")
        (self.root / "tests/gate_contract.py").write_text("")
        self.log = self.root / "ran.log"

    def ran(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_real_memory_cap_probes_are_selected_only_in_live_mode(self):
        import test_job_cap
        import test_memory_cap
        loader = unittest.TestLoader()
        for module, case, method in (
                (test_memory_cap, "MemoryCap",
                 "check_unbounded_allocator_ends_fail_and_the_seat_slice_shows_no_pressure"),
                (test_job_cap, "JobCap",
                 "check_a_runaway_dies_alone_and_its_seat_and_the_next_seat_go_on")):
            self.assertNotIn(method, loader.getTestCaseNames(getattr(module, case)))
            selected = loader.loadTestsFromName(f"{case}.{method}", module)
            self.assertEqual(selected.countTestCases(), 1)
            calls = [number for number, line in enumerate(SMOKE.splitlines())
                     if f'"$REPO/tests/{module.__name__}.py"' in line]
            self.assertEqual(len(calls), 1)
            call = SMOKE.splitlines()[calls[0]]
            self.assertIn(call, suite_shares.smoke_source(SMOKE, REPO, (1, 1), live=True))
            self.assertNotIn(call, suite_shares.smoke_source(SMOKE, REPO, (1, 1)))
            self.assertIn(f"{case}.{method}", SMOKE)

    def test_live_sh_starts_the_live_mode_and_keeps_its_verdict(self):
        live = self.root / "tests/live.sh"
        live.write_text((REPO / "tests/live.sh").read_text())
        # the real accounting, as smoke.sh's own last line `finish` gives it
        self.assertTrue(SMOKE.rstrip().endswith("\nfinish"))
        (self.root / "tests/smoke.sh").write_text(
            'echo "live=${AGENTKIT_SMOKE_LIVE:-}" >>"$ACME_LOG"\n'
            f'WORK="$ACME_WORK"; . "{REPO}/tests/acceptance.sh"\n'
            'ok "1 acme"\n'
            'case $ACME_VERDICT in fail) no "4 acme" ;; skip) skip "3a acme: spent" ;; esac\n'
            'finish\n')
        for verdict, required, code in (("pass", "1", 0), ("fail", "1", 1), ("skip", "1", 2),
                                        ("skip", "0", 0)):
            with self.subTest(verdict=verdict, required=required):
                work = self.root / f"work-{verdict}-{required}"
                work.mkdir()
                env = dict(os.environ, ACME_LOG=str(self.log), ACME_WORK=str(work),
                           ACME_VERDICT=verdict, AGENTKIT_ACCEPTANCE_REQUIRED=required)
                env.pop("AGENTKIT_SMOKE_LIVE", None)
                proc = subprocess.run(["bash", "tests/live.sh"], cwd=self.root, env=env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
                self.assertEqual(self.ran()[-1], "live=1")

    def test_tests_line_cuts_the_network_and_requires_complete_acceptance(self):
        line = gitcall.declared(REPO, "tests")
        self.assertIn("unshare --user --map-current-user --net --keep-caps", line)
        self.assertIn("AGENTKIT_ACCEPTANCE_REQUIRED=1", line)
        tools = self.root / "bin"
        tools.mkdir()
        # a host that allows the namespace, unless ACME_NO_NAMESPACE says it does not
        tool(tools, "unshare", '[ "$1 $2 $3 $4" = "--user --map-current-user --net --keep-caps" ] '
             '&& [ -z "${ACME_NO_NAMESPACE:-}" ] || exit 1\nshift 4; ACME_NS=1 exec "$@"\n')
        tool(tools, "ip", '[ "$*" = "link set lo up" ] && [ "${ACME_NS:-}" = 1 ] || exit 1\n'
             'echo "lo up" >>"$ACME_LOG"\n')
        tool(tools, "setpriv", '[ "$1 $2" = "--inh-caps=-all --ambient-caps=-all" ] || exit 1\n'
             'shift 2; ACME_CAPS=dropped exec "$@"\n')
        said = '"ns=${ACME_NS:-} caps=${ACME_CAPS:-} required=${AGENTKIT_ACCEPTANCE_REQUIRED:-}"'
        (self.root / "tests/smoke.sh").write_text(
            f'echo "smoke "{said} >>"$ACME_LOG"\nexit "${{ACME_SMOKE:-0}}"\n')
        (self.root / "tests/every_file.py").write_text(
            "import os, sys\ne = os.environ.get\n"
            "with open(e('ACME_LOG'), 'a') as fh:\n"
            "    fh.write(f\"every_file ns={e('ACME_NS', '')} caps={e('ACME_CAPS', '')} \"\n"
            "             f\"required={e('AGENTKIT_ACCEPTANCE_REQUIRED', '')}\\n\")\n"
            "sys.exit(int(e('ACME_EVERY', '0')))\n")
        cases = (({}, 0, "ns=1 caps=dropped"), ({"ACME_SMOKE": "3"}, 3, "ns=1 caps=dropped"),
                 ({"ACME_SMOKE": "3", "ACME_EVERY": "1"}, 1, "ns=1 caps=dropped"),
                 ({"ACME_NO_NAMESPACE": "1", "ACME_SMOKE": "3"}, 3, "ns= caps="))
        for extra, code, where in cases:
            with self.subTest(**extra):
                self.log.unlink(missing_ok=True)
                env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
                           ACME_LOG=str(self.log), **extra)
                env.pop("AGENTKIT_ACCEPTANCE_REQUIRED", None)
                proc = subprocess.run(["bash", "-c", line], cwd=self.root, env=env,
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
                ran = self.ran()
                self.assertCountEqual([entry for entry in ran if entry != "lo up"],
                                      [f"smoke {where} required=1", f"every_file {where} required=1"])
                # the probe and the suite each bring loopback up in their own namespace
                self.assertEqual(ran.count("lo up"), 0 if extra.get("ACME_NO_NAMESPACE") else 2)


if __name__ == "__main__":
    unittest.main()

"""The landing suite reaches nothing outside the host; tests/live.sh runs the checks that need it.

Neither suite runs here.  smoke.sh is read, its live blocks found as tests/every_file.py finds
them; tests/live.sh and the AGENTS.md `tests:` line run against stand-in suites, and the
namespace they ask for against a stand-in `unshare`, `ip` and `setpriv`.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import every_file
from agentkit import run

SMOKE = (REPO / "tests/smoke.sh").read_text()
# real models, GitHub, Discord, live meters, the host's shared browser
OUTSIDE = {"1", "2", "3", "3a", "4", "4b", "4c", "4d", "5", "6", "6b", "6d",
           "31a", "31d", "31e"}
# a check's verdict, or the labels a helper or a loop gives it: `ok "4b ...`, `skip_spent 4/4b`
VERDICT = re.compile(r'\b(?:ok|no|skip)\s+"(\d+[a-z]?)[\s:]')
LABELS = re.compile(r'\b(?:skip_checks|skip_unavailable|skip_spent|skip_refused|CHECKS=)\s*"?'
                    r'(\d+[a-z]?(?:/\d+[a-z]?)*)[\s":;]')


def checks():
    """(line number, label) of every check smoke.sh names a verdict for."""
    for number, line in enumerate(SMOKE.splitlines()):
        for label in VERDICT.findall(line) + [one for group in LABELS.findall(line)
                                              for one in group.split("/")]:
            yield number, label


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
        (self.root / "tests/landing.py").write_text((REPO / "tests/landing.py").read_text())
        self.log = self.root / "ran.log"

    def ran(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_outside_checks_run_only_in_the_live_mode_and_every_other_in_both(self):
        live = every_file.live_blocks(SMOKE)
        found = {}
        for number, label in checks():
            found.setdefault(label, set()).add(number in live)
        self.assertEqual(OUTSIDE - set(found), set(), "an outside check is gone from smoke.sh")
        self.assertEqual({label for label, where in found.items() if True in where}, OUTSIDE)
        self.assertEqual({label for label, where in found.items() if False in where} & OUTSIDE,
                         set())
        # nothing else reads the mode, so every check outside the live blocks runs in both
        modal = [line for line in SMOKE.splitlines()
                 if "AGENTKIT_SMOKE_LIVE" in line and not line.lstrip().startswith("#")]
        self.assertEqual(set(modal), {every_file.LIVE})

    def test_a_live_block_runs_nothing_outside_the_live_mode(self):
        lines = SMOKE.splitlines()
        live = sorted(every_file.live_blocks(SMOKE))
        blocks = [[live[0]]]
        for number in live[1:]:
            if number == blocks[-1][-1] + 1:
                blocks[-1].append(number)
            else:
                blocks.append([number])
        self.assertEqual(len(blocks), 5)
        stub = 'ok() { echo "ran: $*"; }; no() { ok "$@"; }; skip() { ok "$@"; }\n'
        for block in blocks:
            text = "\n".join(lines[block[0]:block[-1] + 1])
            for mode in ("", "0"):
                with self.subTest(line=block[0] + 1, mode=mode):
                    env = {k: v for k, v in os.environ.items() if k != "AGENTKIT_SMOKE_LIVE"}
                    if mode:
                        env["AGENTKIT_SMOKE_LIVE"] = mode
                    proc = subprocess.run(["bash", "-c", "set -uo pipefail\n" + stub + text],
                                          env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

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
        line = run.declared(REPO, "tests")
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

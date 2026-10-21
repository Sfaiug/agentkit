"""A live check runs only what needs the outside world, and the landing suite everything else.

tests/live.sh runs the checks tests/suite_shares.py's LIVE_CHECKS names, with their declared
dependencies and the shared setup; the landing suite runs every other check; so each check runs
in exactly one of the two.  Offline: smoke.sh is read and chosen from as its entry chooses, and
that entry runs on a stand-in suite with a fixture per real check, in a temporary checkout.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares as suite

SMOKE = (REPO / "tests/smoke.sh").read_text()
BLOCKS = suite.smoke_blocks(SMOKE)
NAMED = {name for name, _ in BLOCKS if name is not None}
# a check's verdict, or the labels a helper or a loop gives it: `ok "4b ...`, `skip_spent 4/4b`
VERDICT = re.compile(r'\b(?:ok|no|skip)\s+"(\d+[a-z]?)[\s:]')
LABELS = re.compile(r'\b(?:skip_checks|skip_unavailable|skip_spent|skip_refused|CHECKS=)\s*"?'
                    r'(\d+[a-z]?(?:/\d+[a-z]?)*)[\s":;]')


def labels(source):
    """Every check label a verdict in the source names."""
    found = set()
    for line in source.splitlines():
        found.update(VERDICT.findall(line))
        found.update(one for group in LABELS.findall(line) for one in group.split("/"))
    return found


class LiveCheckRunsOnlyLive(unittest.TestCase):
    def test_each_check_is_chosen_by_exactly_one_mode(self):
        live = set(suite.smoke_owners(BLOCKS, REPO, 1, live=True))
        landing = set(suite.smoke_owners(BLOCKS, REPO, 1))
        self.assertEqual(live, suite.LIVE_CHECKS)
        self.assertEqual(live & landing, set())
        self.assertEqual(live | landing, NAMED)
        # what a live check depends on runs beside it, never left to the landing suite alone
        for group in suite.DEPENDENCIES:
            if live & set(group):
                self.assertLessEqual(set(group), live, group)

    def test_every_check_label_runs_in_one_mode(self):
        live = labels(suite.smoke_source(SMOKE, REPO, (1, 1), live=True))
        landing = labels(suite.smoke_source(SMOKE, REPO, (1, 1)))
        # check 0 is the tmux guard every mode and piece runs before anything else
        self.assertEqual(live & landing, {"0"})
        self.assertEqual(live | landing, labels(SMOKE))
        # no check reads the mode itself, so none hides a live branch inside a landing check
        self.assertEqual([line for line in SMOKE.splitlines() if "AGENTKIT_SMOKE_LIVE" in line
                          and not line.lstrip().startswith("#")], [])

    def test_the_entry_runs_its_modes_checks_alone(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-live-only-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        for name in ("live.sh", "suite_shares.py"):
            (root / "tests" / name).write_text((REPO / "tests" / name).read_text())
        # the real entry and setup, then one fixture per real check that says it ran
        stub = SMOKE[:SMOKE.index('export PATH="$REPO/bin:$PATH"')]
        stub += "".join(f"# --- {name}: fixture\necho 'ran {name}'\n" for name in sorted(NAMED))
        (root / "tests/smoke.sh").write_text(stub)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))}
        env["HOME"] = str(root)
        ran = {}
        for script in ("live.sh", "smoke.sh"):
            proc = subprocess.run(["bash", f"tests/{script}"], cwd=root, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            ran[script] = [line.removeprefix("ran ") for line in proc.stdout.splitlines()]
        self.assertCountEqual(ran["live.sh"], suite.LIVE_CHECKS)
        self.assertCountEqual(ran["smoke.sh"], NAMED - suite.LIVE_CHECKS)

    def test_landing_rule_reads_the_one_list(self):
        rule = " ".join((REPO / "tests/test_repo_suite.py").read_text().split())
        self.assertIn("(`LIVE_CHECKS` in `tests/suite_shares.py`, run by `tests/live.sh`)", rule)


if __name__ == "__main__":
    unittest.main()

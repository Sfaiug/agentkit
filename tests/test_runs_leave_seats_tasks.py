"""Runs never take the tasks a seat needs: the runs slice's TasksMax leaves the seats' share
of agentkit.slice's ceiling, in its drop-in and at once at runtime.

Offline: install.sh's slice section runs in a temporary HOME against a fake systemctl that
loads the slice's drop-ins at a reload, as systemd does, and records what is set at runtime.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SYSTEMCTL = '''#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
path = pathlib.Path(os.environ["FAKE_UNITS"])
units = json.loads(path.read_text()) if path.exists() else {{}}
if args == ["--user", "is-system-running"]:
    print("running")
elif args[:1] == ["show"]:
    print(os.environ["FAKE_USER_TASKS"])
elif args == ["--user", "daemon-reload"]:
    # systemd reads the slice's drop-ins in name order, and the last TasksMax wins
    ceiling = "infinity"
    dropins = pathlib.Path(os.environ["HOME"], ".config/systemd/user/agentkit.slice.d")
    for conf in sorted(dropins.glob("*.conf")):
        for line in conf.read_text().splitlines():
            if line.startswith("TasksMax="):
                ceiling = line.split("=", 1)[1]
    units.setdefault("agentkit.slice", {{}})["TasksMax"] = ceiling
elif args[:3] == ["--user", "show", "agentkit.slice"]:
    print(units.get("agentkit.slice", {{}}).get("TasksMax", "infinity"))   # as last loaded
elif "set-property" in args:
    unit = next(arg for arg in args if arg.endswith(".slice"))
    units.setdefault(unit, {{}}).update(arg.split("=", 1) for arg in args if "=" in arg)
path.write_text(json.dumps(units))
'''


class RunsLeaveSeatsTasks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-runs-leave-seats-tasks-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bindir = self.root / "bin"
        bindir.mkdir()
        (bindir / "systemctl").write_text(SYSTEMCTL.format(python=sys.executable))
        (bindir / "systemctl").chmod(0o755)
        (self.root / ".agentkit").mkdir()
        self.units = self.root / "units.json"
        self.user = self.root / ".config/systemd/user"
        self.env = {**os.environ, "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / ".config"),
                    "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_UNITS": str(self.units),
                    "FAKE_USER_TASKS": "5100"}

    def install(self, pins=""):
        (self.root / ".agentkit/config.toml").write_text(pins)
        source = (REPO / "install.sh").read_text()
        body = source[source.index("# --- (g3) the ceiling"):source.index("# --- (h) a new phone key")]
        prelude = ("set -euo pipefail\nROLE=server\nSANDBOX=0\n"
                   f"REPO={shlex.quote(str(REPO))}\n"
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "$*" >&2; }\n')
        result = subprocess.run(["bash", "-c", prelude + body], capture_output=True, text=True,
                                timeout=60, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def dropin(self, child):
        text = (self.user / f"{child}.d/weights.conf").read_text()
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def assert_runs_leave_seats(self, ceiling):
        # One share for seats: the memory they keep is the part of the tasks runs never take.
        share = int(self.dropin("agentkit-seats.slice")["MemoryLow"].rstrip("%"))
        self.assertGreater(share, 0)
        want = "infinity" if ceiling == "infinity" else str(int(ceiling) * (100 - share) // 100)
        self.assertEqual(self.dropin("agentkit-runs.slice")["TasksMax"], want)
        self.assertEqual(json.loads(self.units.read_text())["agentkit-runs.slice"]["TasksMax"], want)

    def test_runs_leave_seats_a_share_of_the_derived_ceiling(self):
        self.install()
        limits = (self.user / "agentkit.slice.d/limits.conf").read_text()
        self.assertIn("TasksMax=3825\n", limits)        # three quarters of the user unit's 5100
        self.assertLess(int(self.dropin("agentkit-runs.slice")["TasksMax"]), 3825)
        self.assert_runs_leave_seats("3825")

    def test_runs_follow_a_pinned_ceiling(self):
        for pin in ("1000", "infinity", "2000"):
            with self.subTest(pin=pin):
                self.install(f'slice_tasks_max = "{pin}"\n')
                self.assert_runs_leave_seats(pin)

    def test_an_owners_limits_file_sets_the_ceiling(self):
        limits = self.user / "agentkit.slice.d/limits.conf"
        limits.parent.mkdir(parents=True)
        limits.write_text("[Slice]\nTasksMax=1200\n")
        self.units.write_text(json.dumps({"agentkit.slice": {"TasksMax": "3825"}}))  # not reloaded yet
        self.install()
        self.assertEqual(limits.read_text(), "[Slice]\nTasksMax=1200\n")
        self.assert_runs_leave_seats("1200")

    def test_an_owners_runs_dropin_is_left_alone(self):
        runs = self.user / "agentkit-runs.slice.d/weights.conf"
        runs.parent.mkdir(parents=True)
        runs.write_text("[Slice]\nTasksMax=5\n")
        self.install()
        self.assertEqual(runs.read_text(), "[Slice]\nTasksMax=5\n")
        self.assertNotIn("agentkit-runs.slice", json.loads(self.units.read_text()))


if __name__ == "__main__":
    unittest.main()

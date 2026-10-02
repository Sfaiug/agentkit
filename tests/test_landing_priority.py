"""The run holding a repository's merge turn outweighs every other run until it lets go.  Offline.

A fake cgroup tree (AK_CGROUP_ROOT) holds the test server's slices, and a fake `systemctl` on
PATH records its argv and writes the weight into that tree as the user manager would.  No real
manager is asked, no real unit or cgroup is touched.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

UID = os.getuid()
SLICE = f"user.slice/user-{UID}.slice/user@{UID}.service/agentkit.slice/agentkit-test.slice"
SYSTEMCTL = '''#!{python}
import os, pathlib, sys
with open(os.environ["ACME_SYSTEMCTL_LOG"], "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
unit, weight = sys.argv[-2], sys.argv[-1].split("=")[1]
pathlib.Path(os.environ["ACME_RUNS"], unit, "cpu.weight").write_text(weight + "\\n")
'''


class LandingPriority(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-landing-priority-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        slice_dir = self.root / "cgroup" / SLICE
        self.runs = slice_dir / "agentkit-test-runs.slice"
        self.weigh(slice_dir / "agentkit-test-seats.slice", 100)
        self.weigh(self.runs, 40)
        (slice_dir / "cpu.max").write_text("800000 100000\n")      # 8 cores
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "systemctl").write_text(SYSTEMCTL.format(python=sys.executable))
        (bin_dir / "systemctl").chmod(0o755)
        self.calls = self.root / "systemctl.log"
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AK_CGROUP_ROOT": str(self.root / "cgroup"),
            "AK_CGROUP_FILE": str(self.root / "no-cgroup"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACME_SYSTEMCTL_LOG": str(self.calls), "ACME_RUNS": str(self.runs)}))
        self.wt = self.root / "acme"
        self.wt.mkdir()
        subprocess.run(["git", "init", "-q", str(self.wt)], check=True)
        self.logs = []

    def weigh(self, cgroup, weight):
        cgroup.mkdir(parents=True, exist_ok=True)
        (cgroup / "cpu.weight").write_text(f"{weight}\n")

    def weight(self, cgroup):
        return int((cgroup / "cpu.weight").read_text())

    def loop(self, scope="agentkit-run-acme"):
        state = {"repo": str(self.wt), **({"scope": scope} if scope else {})}
        return SimpleNamespace(wt=self.wt, state=state, run_dir=None, log=self.logs.append,
                               write=lambda: None)

    def said(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_the_holder_outweighs_every_other_run_until_it_lets_go(self):
        holder = self.runs / "agentkit-run-acme.scope"
        self.weigh(holder, 40)
        self.weigh(self.runs / "agentkit-run-fix-api.scope", 40)
        self.weigh(self.runs / "agentkit-job-widget.scope", 60)
        with run.merge_turn(self.loop(), "origin/main"):
            # the others' 100 together, times the slice's 8 cores and one
            self.assertEqual(self.weight(holder), 900)
        self.assertEqual(self.weight(holder), 40)
        self.assertEqual(self.said(), [
            "--user set-property --runtime agentkit-run-acme.scope CPUWeight=900",
            "--user set-property --runtime agentkit-run-acme.scope CPUWeight=40"])
        # the seats keep their weight over the runs slice, which nothing raised
        self.assertEqual(self.weight(self.runs), 40)
        self.assertEqual(self.weight(self.runs.parent / "agentkit-test-seats.slice"), 100)
        self.assertTrue(any("CPU weight 900 while holding the merge turn" in line
                            for line in self.logs), self.logs)

    def test_a_reserved_lap_that_lets_go_early_comes_back_down(self):
        holder = self.runs / "agentkit-run-acme.scope"
        self.weigh(holder, 40)
        self.weigh(self.runs / "agentkit-run-fix-api.scope", 40)
        with run.merge_turn(self.loop(), "origin/main", reserve=True):
            self.assertEqual(self.weight(holder), 360)
            run.drop_reserved_turn()
            self.assertEqual(self.weight(holder), 40)
        self.assertEqual(len(self.said()), 2)

    def test_the_raise_stops_at_the_kernels_top_weight(self):
        holder = self.runs / "agentkit-run-acme.scope"
        self.weigh(holder, 40)
        for n in range(30):
            self.weigh(self.runs / f"agentkit-run-fix-api-{n}.scope", 40)
        with run.merge_turn(self.loop(), "origin/main"):
            self.assertEqual(self.weight(holder), 10000)
        self.assertEqual(self.weight(holder), 40)

    def test_nothing_changes_without_a_scope_a_cgroup_or_another_run(self):
        self.weigh(self.runs / "agentkit-run-acme.scope", 40)
        for scope in (None, "none", "agentkit-run-gone"):
            with self.subTest(scope=scope), run.merge_turn(self.loop(scope), "origin/main"):
                pass
        # alone in the runs slice, there is nobody to outweigh
        with run.merge_turn(self.loop(), "origin/main"):
            pass
        # a Mac: no cgroup tree at all
        with patch.dict(os.environ, {"AK_CGROUP_ROOT": str(self.root / "nowhere")}), \
                run.merge_turn(self.loop(), "origin/main"):
            pass
        self.assertEqual(self.said(), [])
        self.assertEqual(self.weight(self.runs / "agentkit-run-acme.scope"), 40)


if __name__ == "__main__":
    unittest.main()

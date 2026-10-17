"""A sharded suite runs its pieces on the suite helper when it has room; what the helper loses
or fails runs again here, and decides. Offline: a fake `ssh` plays the helper, fake Mac tools.
"""

from contextlib import ExitStack
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, helper, worker

SUITE = 'printf "piece %s\\n" "${AK_SHARD:-all}"'

# The helper: room for three pieces; a piece says it ran there, or exits as its `code-K` says.
FAKE_SSH = r"""#!/bin/bash
here=$(dirname "$0")
eval "set -- $2"
echo "$5" >>"$here/calls"
case $5 in
probe) printf 'cpus 3\nload 0\nmemory_mb 1048576\nfree_percent 100\ntaken_cpus 0\ntaken_mb 0\n' ;;
prepare) cat >"$here/parcel.tar" ;;
run) [ -e "$here/code-${11%/*}" ] && exit "$(cat "$here/code-${11%/*}")"
  echo "helper ran ${11}"; AK_SHARD=${11} exec bash -c "${15}" ;;
esac
"""

# The Mac's own tools, for tools/helper/mac.sh's probe run here.
MAC_TOOLS = {
    "pmset": "echo \"Now drawing from '$FAKE_POWER'\"",
    "sysctl": 'case "$2" in hw.ncpu) echo 10;; vm.loadavg) echo "{ 1.00 2.50 3.00 }";;'
              ' hw.memsize) echo 17179869184;; esac',
    "memory_pressure": 'echo "System-wide memory free percentage: 50%"',
    "container": 'case "$1" in system) exit 0;; ls)\n'
                 'echo "ID IMAGE OS ARCH STATE IP CPUS MEMORY STARTED"\n'
                 'echo "ak-1a2b-1-2 ak-helper:abc linux arm64 running 10.0.0.2/24 2 2048 MB now"\n'
                 'echo "owners img linux arm64 running 192.168.64.3/24 4 4 GB now";; esac',
    "ssh": 'exec bash -c "$2"',
}


class SuiteHelper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-suite-helper-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_CGROUP_FILE": str(self.root / "none"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.01))
        self.repo = self.root / "repo"
        git = ["git", "-C", str(self.repo), "-c", "user.name=acme", "-c", "user.email=a@acme.test"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "start"], check=True)
        subprocess.run([*git, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        subprocess.run([*git, "remote", "set-head", "origin", "main"], check=True)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "ssh").write_text(FAKE_SSH)
        (self.fake / "ssh").chmod(0o755)
        self.stack.enter_context(patch.object(helper, "SSH", (str(self.fake / "ssh"),)))
        self.turns = []
        self.stack.enter_context(patch.object(
            gate, "_acquire_gate_turn", side_effect=lambda *a, **kw: self.turns.append(a)))
        (config.HOME / config.CONFIG_NAME).write_text('suite_helper = "acme-mac"\n')

    def check(self, codes):
        for path in [*self.fake.glob("code-*"), self.fake / "calls"]:
            path.unlink(missing_ok=True)
        for piece, code in codes.items():
            (self.fake / f"code-{piece}").write_text(str(code))
        self.turns.clear()
        logs = []
        code, text, _ = gate.run_suite(SUITE, 30, cwd=self.repo, activity=self.root / "live.log",
                                       output=io.BytesIO(), log=logs.append)
        self.assertEqual(code, 0, text)
        return text, [line for line in logs if "WARN" in line]

    def test_pieces_run_on_the_helper_and_take_no_turn_here(self):
        text, warned = self.check({})
        for shard in ("1/3", "2/3", "3/3"):
            self.assertIn(f"--- AK_SHARD={shard} ---\n[exit 0]\nhelper ran {shard}\npiece {shard}",
                          text)
        self.assertEqual((self.turns, warned), ([], []))
        verbs = (self.fake / "calls").read_text().split()
        self.assertEqual((verbs[:2], verbs.count("run"), verbs[-1]),
                         (["probe", "prepare"], 3, "finish"))
        with tarfile.open(self.fake / "parcel.tar") as tar:
            tar.extractall(self.fake / "parcel")
        heads = subprocess.run(["git", "bundle", "list-heads", "parcel/repo.bundle"], cwd=self.fake,
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(heads[1::2], ["HEAD", "refs/remotes/origin/main"])

    def test_what_the_helper_loses_or_fails_runs_here_on_a_turn(self):
        for codes, warn in (({2: helper.LOST}, []), ({2: 1}, ["WARN AK_SHARD=2/3"])):
            with self.subTest(codes=codes):
                text, warned = self.check(codes)
                self.assertIn("--- AK_SHARD=2/3 ---\n[exit 0]\npiece 2/3", text)
                self.assertIn("helper ran 1/3", text)
                self.assertEqual(len(self.turns), 1)
                self.assertEqual([line[:17] for line in warned], warn)

    def test_no_helper_named_runs_here(self):
        (config.HOME / config.CONFIG_NAME).write_text("")
        self.assertNotIn("helper ran", self.check({})[0])
        self.assertFalse((self.fake / "calls").exists())


class HelperProbe(unittest.TestCase):
    def test_probe_leaves_load_other_suites_half_the_free_memory_and_battery(self):
        with tempfile.TemporaryDirectory(prefix="ak-test-helper-probe-") as tmp:
            for name, body in MAC_TOOLS.items():
                (Path(tmp) / name).write_text(f"#!/bin/bash\n{body}\n")
                (Path(tmp) / name).chmod(0o755)
            with patch.object(helper, "SSH", (f"{tmp}/ssh",)), patch.dict(os.environ, {
                    "PATH": f"{tmp}:{os.environ['PATH']}", "FAKE_POWER": "AC Power"}):
                # 10 CPUs less another suite's 2; 8 GiB free, half of it less that suite's 2.
                self.assertEqual(helper.room("acme-mac", 1.0, 500), (2, 4, 1024))
                self.assertIsNone(helper.room("acme-mac", 1.0, 2000))
                os.environ["FAKE_POWER"] = "Battery Power"
                self.assertIsNone(helper.room("acme-mac", 1.0, 500))


if __name__ == "__main__":
    unittest.main()

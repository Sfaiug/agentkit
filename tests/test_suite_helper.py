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
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.clock import Clock
from fixtures.sandbox import account_home
from agentkit import config, gate, helper, worker

SUITE = 'printf "piece %s\\n" "${AK_SHARD:-all}"'

# The helper: room for three pieces; a piece says it ran there, or exits as its `code-K` says.
FAKE_SSH = r"""#!/bin/bash
here=$(dirname "$0")
eval "set -- $2"
echo "$5" >>"$here/calls"
case $5 in
probe) printf 'cpus 6\nload 0\nmemory_mb 1048576\nfree_percent 100\n' ;;
prepare) cat >"$here/parcel.tar" ;;
run) [ -e "$here/code-${11%/*}" ] && exit "$(cat "$here/code-${11%/*}")"
  echo "helper ran ${11}"; AK_SHARD=${11} exec bash -c "${15}" ;;
esac
"""

# The Mac's own tools, for tools/helper/mac.sh run here: on its charger for the first
# $FAKE_AC_CALLS readings; a VM comes up a second after `container run`, noting any VM up
# already, and runs until stopped.
MAC_TOOLS = {
    "pmset": 'n=$(( $(cat "$FAKE/readings" 2>/dev/null || echo 0) + 1 )); echo $n >"$FAKE/readings"\n'
             '[ $n -le "$FAKE_AC_CALLS" ] && echo "Now drawing from \'AC Power\'" ||'
             ' echo "Now drawing from \'Battery Power\'"',
    "sysctl": 'case "$2" in hw.ncpu) echo 10;; vm.loadavg) echo "{ 1.00 2.50 3.00 }";;'
              ' hw.memsize) echo 17179869184;; esac',
    "memory_pressure": 'echo "System-wide memory free percentage: 50%"',
    "caffeinate": 'shift; exec "$@"',
    "container": 'case "$1 $2" in "system "*|"builder "*) exit 0;;\n'
                 '"image inspect") [ -e "$FAKE/has-${3##*/}" ];;\n'
                 '"build "*) touch "$FAKE/has-debian:trixie-slim"\n'
                 '  [ ! -e "$FAKE/broken" ] && touch "$FAKE/has-ak-helper:new";;\n'
                 '"image ls") printf "NAME TAG DIGEST\\nak-helper new 1\\nak-helper old 2\\n'
                 'acme-local unpublished 3\\n";;\n'
                 '"image delete") echo "$3" >>"$FAKE/deleted"; rm -f "$FAKE/has-${3##*/}";;\n'
                 '"run "*) while [ "$1" != --name ]; do shift; done\n'
                 '  sleep 1; ls "$FAKE" | grep "^vm-" >>"$FAKE/overlap"; touch "$FAKE/vm-$2"\n'
                 '  while [ -e "$FAKE/vm-$2" ]; do sleep 0.1; done;;\n'
                 '"stop "*) rm "$FAKE/vm-$2";; esac',
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
        self.git = git = ["git", "-C", str(self.repo), "-c", "user.name=acme",
                          "-c", "user.email=a@acme.test"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "start"], check=True)
        subprocess.run([*git, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        subprocess.run([*git, "remote", "set-head", "origin", "main"], check=True)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "ssh").write_text(FAKE_SSH)
        (self.fake / "ssh").chmod(0o755)
        self.stack.enter_context(patch.object(helper, "SSH", (str(self.fake / "ssh"),)))
        self.turns, self.waited = [], 0.0
        clock = Clock(time.sleep)
        clock.monotonic = lambda: time.monotonic() + self.waited
        self.stack.enter_context(patch.object(gate, "time", clock))
        self.stack.enter_context(patch.object(gate, "_acquire_gate_turn", side_effect=self.turn))
        (config.HOME / config.CONFIG_NAME).write_text('suite_helper = "acme-mac"\n')

    def turn(self, *args, **_kw):
        # A turn here comes after longer than the suite's ceiling, which no wait is charged to.
        self.turns.append(args)
        self.waited += 60

    def check(self, codes, suite=SUITE):
        for path in [*self.fake.glob("code-*"), self.fake / "calls"]:
            path.unlink(missing_ok=True)
        for piece, code in codes.items():
            (self.fake / f"code-{piece}").write_text(str(code))
        self.turns.clear()
        logs = []
        code, text, _ = gate.run_suite(suite, 30, cwd=self.repo, activity=self.root / "live.log",
                                       output=io.BytesIO(), log=logs.append,
                                       stderr=subprocess.STDOUT)
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

    def test_a_piece_that_changes_its_checkout_there_fails_there(self):
        (self.repo / "tracked").write_text("committed\n")
        subprocess.run([*self.git, "add", "tracked"], check=True)
        subprocess.run([*self.git, "commit", "-qm", "tracked"], check=True)
        warned = self.check({}, SUITE + "; echo altered >>tracked")[1]
        self.assertEqual(sorted(line[:17] for line in warned),
                         [f"WARN AK_SHARD={k}/3" for k in (1, 2, 3)])

    def test_no_helper_named_runs_here(self):
        (config.HOME / config.CONFIG_NAME).write_text("")
        self.assertNotIn("helper ran", self.check({})[0])
        self.assertFalse((self.fake / "calls").exists())


class HelperMac(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-helper-mac-")
        self.addCleanup(tmp.cleanup)
        self.fake = Path(tmp.name)
        for name, body in MAC_TOOLS.items():
            (self.fake / name).write_text(f"#!/bin/bash\n{body}\n")
            (self.fake / name).chmod(0o755)
        self.root = self.fake / ".agentkit-helper"
        for context in (patch.object(helper, "SSH", (str(self.fake / "ssh"),)), patch.dict(
                os.environ, {"PATH": f"{self.fake}:{os.environ['PATH']}", "HOME": str(self.fake),
                             "FAKE": str(self.fake), "FAKE_AC_CALLS": "99"})):
            context.start()
            self.addCleanup(context.stop)

    def test_probe_leaves_load_half_the_free_memory_battery_and_a_held_mac(self):
        # 10 CPUs less a load of 1; half of 8 GiB free.
        self.assertEqual(helper.room("acme-mac", 1.0, 500), (4, 2, 1024))
        # a small piece still gets two CPUs: 9 spare make 4 VMs, not 9 of one CPU
        self.assertEqual(helper.room("acme-mac", 1.0, 100), (4, 2, 1024))
        self.assertIsNone(helper.room("acme-mac", 1.0, 2100))
        (self.root / "other").mkdir(parents=True)
        (self.root / "other" / "held").touch()
        self.assertIsNone(helper.room("acme-mac", 1.0, 500))
        os.utime(self.root / "other" / "held", (time.time() - 600,) * 2)
        self.assertIsNotNone(helper.room("acme-mac", 1.0, 500))
        os.environ["FAKE_AC_CALLS"] = "0"
        self.assertIsNone(helper.room("acme-mac", 1.0, 500))

    def test_one_suite_holds_the_mac_and_only_its_own_old_image_goes(self):
        parcel = io.BytesIO()
        with tarfile.open(fileobj=parcel, mode="w") as tar:
            tar.add(REPO / "tools" / "helper" / "Containerfile", "image/Containerfile")
        prepare = lambda key: helper._remote("acme-mac", "prepare", key, "ak-helper:new",
                                             input=parcel.getvalue()).returncode
        # a failed build keeps the helper's old image and drops the base it fetched
        (self.fake / "broken").touch()
        self.assertEqual(prepare("broken"), helper.LOST)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "docker.io/library/debian:trixie-slim\n")
        (self.fake / "broken").unlink()
        (self.fake / "deleted").unlink()
        self.assertEqual(prepare("first"), 0)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "ak-helper:old\ndocker.io/library/debian:trixie-slim\n")
        self.assertIsNone(helper.room("acme-mac", 1.0, 500))
        self.assertEqual(prepare("second"), helper.LOST)
        for key in ("first", "second"):
            helper.finish(helper.Away("acme-mac", key, *[None] * 6))
        self.assertEqual(prepare("third"), 0)
        # a base the owner had before the build stays
        helper.finish(helper.Away("acme-mac", "third", *[None] * 6))
        (self.fake / "has-ak-helper:new").unlink()
        (self.fake / "has-debian:trixie-slim").touch()
        (self.fake / "deleted").unlink()
        self.assertEqual(prepare("fourth"), 0)
        self.assertEqual((self.fake / "deleted").read_text(), "ak-helper:old\n")

    def test_a_piece_waits_while_another_suite_holds_the_mac(self):
        def start(key):
            (self.root / key).mkdir(parents=True)
            (self.root / key / "held").touch()    # its claim, as `prepare` leaves it
            return subprocess.Popen(helper._remote("acme-mac", "run", key, "ak-helper:new",
                                                   f"ak-{key}", 1, 512), stdout=subprocess.DEVNULL)

        def up(name):
            deadline = time.monotonic() + 30
            while not (self.fake / name).exists():
                self.assertLess(time.monotonic(), deadline, f"{name} never came up")
                time.sleep(0.1)
            return self.fake / name

        first = start("first")
        up("vm-ak-first")
        second = start("second")
        time.sleep(3)   # the second VM would be up beside the first by now, were it let
        up("vm-ak-first").unlink()
        up("vm-ak-second").unlink()
        self.assertEqual((first.wait(30), second.wait(30)), (0, 0))
        self.assertEqual((self.fake / "overlap").read_text(), "")

    def test_a_vm_that_comes_up_after_its_charger_went_stops(self):
        (self.root / "key").mkdir(parents=True)
        os.environ["FAKE_AC_CALLS"] = "1"
        run = helper._remote("acme-mac", "run", "key", "ak-helper:new", "ak-key-1-2", 1, 512,
                             timeout=30)
        self.assertEqual(run.returncode, helper.LOST)
        self.assertEqual(list(self.fake.glob("vm-*")), [])


if __name__ == "__main__":
    unittest.main()

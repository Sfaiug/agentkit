"""A sharded suite runs its pieces on the suite helper when it has room; what the helper loses
or fails runs again here, and decides. Offline: a fake `ssh` plays the helper, fake Mac tools.
"""

from contextlib import ExitStack
import io
import os
import shutil
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import threading
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
probe) printf 'cpus 6\nload 0\nroom_mb 524288\n' ;;
prepare) echo "$7" >>"$here/images"; cat >"$here/parcel.tar" ;;
run) [ -e "$here/code-${12%/*}" ] && { echo "acme broke ${12}"; exit "$(cat "$here/code-${12%/*}")"; }
  echo "helper ran ${12}"; AK_SHARD=${12} exec bash -c "${16}" ;;
esac
"""

# The Mac's own tools, for tools/helper/mac.sh run here: on its charger for the first
# $FAKE_AC_CALLS readings; a build takes half a second, and each `container builder` verb, kept in
# $FAKE/builder, breaks any build still running; an image deleted leaves the listing; a VM comes
# up a second after `container run`, or only after a stop while
# $FAKE/stalls, and runs until stopped,
# listed beside the owner's own VM and an ended one, holding half the memory it was given.
# Linux's `flock` takes `lockf`'s place.
MAC_TOOLS = {
    "uname": "echo Darwin",
    "pmset": 'n=$(( $(cat "$FAKE/readings" 2>/dev/null || echo 0) + 1 )); echo $n >"$FAKE/readings"\n'
             '[ $n -le "$FAKE_AC_CALLS" ] && echo "Now drawing from \'AC Power\'" ||'
             ' echo "Now drawing from \'Battery Power\'"',
    "sysctl": 'case "$2" in hw.ncpu) echo 10;; vm.loadavg) echo "{ 1.00 2.50 3.00 }";;'
              ' hw.memsize) echo 17179869184;; esac',
    "memory_pressure": 'echo "System-wide memory free percentage: 50%"',
    "caffeinate": 'shift; exec "$@"',
    "container": 'vms() { { echo "acme-db 4096 running"; echo "ak-ended 4096 stopped"\n'
                 '  for vm in "$FAKE"/vm-*; do mb=$(cat "$vm" 2>/dev/null) && echo "${vm##*/vm-} $mb running"\n'
                 '  done; } | jq -R -s \'split("\\n")[:-1] | map(split(" ")\'\\\n'
                 '\' | {id: .[0], mb: (.[1] | tonumber), state: .[2]})\'; }\n'
                 'case "$1 $2" in "system "*) [ ! -e "$FAKE/system-broken" ];;\n'
                 '"builder "*) echo "$2" >>"$FAKE/builder"; rm -f "$FAKE"/building-*;;\n'
                 '"image inspect") [ -e "$FAKE/has-${3##*/}" ];;\n'
                 '"build "*) touch "$FAKE/has-debian:trixie-slim" "$FAKE/building-$5"; sleep 0.5\n'
                 '  rm "$FAKE/building-$5" && [ ! -e "$FAKE/broken" ] && touch "$FAKE/has-$5";;\n'
                 '"image ls") { printf "NAME TAG DIGEST\\nak-helper new 1\\nak-helper old 2\\n'
                 'acme-local unpublished 3\\nak-helper-other old 4\\n"\n'
                 '  ls "$FAKE" | sed -n "s/^has-\\(.*\\):\\(.*\\)/\\1 \\2 5/p"; } |\n'
                 '  awk -v gone="$(cat "$FAKE/deleted" 2>/dev/null)" \'BEGIN {split(gone, names, "\\n")\n'
                 '    for (i in names) out[names[i]]} !(($1 ":" $2) in out)\';;\n'
                 '"image delete") echo "$3" >>"$FAKE/deleted"; rm -f "$FAKE/has-${3##*/}";;\n'
                 '"ls --all") [ ! -e "$FAKE/ls-broken" ] || exit 1; echo "ID IMAGE OS"\n'
                 '  cat "$FAKE/listed" 2>/dev/null; :;;\n'
                 '"list --all") vms | jq \'map({configuration: {id, resources:\'\\\n'
                 '\' {memoryInBytes: (.mb * 1048576)}}, status: {state}})\';;\n'
                 '"stats --no-stream") vms | jq \'map(select(.state == "running")\'\\\n'
                 '\' | {id, memoryUsageBytes: (.mb * 524288)})\';;\n'
                 '"run "*) while [ "$1" != --name ]; do [ "$1" != --memory ] || mb=${2%m}; shift; done\n'
                 '  sleep 1; while [ -e "$FAKE/stalls" ]; do sleep 0.1; done\n'
                 '  echo "$mb" >"$FAKE/.vm-$2"; mv "$FAKE/.vm-$2" "$FAKE/vm-$2"\n'
                 '  while [ -e "$FAKE/vm-$2" ]; do sleep 0.1; done;;\n'
                 '"stop "*) rm -f "$FAKE/stalls"; rm "$FAKE/vm-$2";; esac',
    "ssh": 'umask 077; exec bash -c "$2"',    # the strictest umask a Mac's shell may have
    "lockf": '[ "$1" != -k ] || shift; exec flock "$@"',
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
        (self.repo / helper.RECIPE).parent.mkdir(parents=True)
        (self.repo / helper.RECIPE).write_text("FROM acme/base\n")
        subprocess.run([*git, "add", helper.RECIPE], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "start"], check=True)
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
        # A question a suite left the helper ends before the checkout it reads goes.
        self.addCleanup(lambda: [thread.join() for thread in threading.enumerate()
                                 if thread.name == gate.ASKING])

    def turn(self, *args, **_kw):
        if not _kw.get("wait", True):
            return None
        # A turn here comes after longer than the suite's ceiling, which no wait is charged to.
        self.turns.append(args)
        self.waited += 60

    def check(self, codes, suite=SUITE):
        for path in [*self.fake.glob("code-*"), self.fake / "calls"]:
            path.unlink(missing_ok=True)
        for piece, code in codes.items():
            (self.fake / f"code-{piece}").write_text(str(code))
        self.turns.clear()
        self.logs = logs = []
        code, text, _ = gate.run_suite(suite, 30, cwd=self.repo, activity=self.root / "live.log",
                                       output=io.BytesIO(), log=logs.append,
                                       stderr=subprocess.STDOUT)
        self.assertEqual(code, 0, text)
        return text, [line for line in logs if "WARN" in line]

    def test_pieces_run_on_the_helper_and_take_no_turn_here(self):
        text, warned = self.check({})
        for shard in (f"{k}/6" for k in range(1, 7)):    # its three VMs take six pieces
            self.assertIn(f"--- AK_SHARD={shard} ---\n[exit 0]\nhelper ran {shard}\npiece {shard}",
                          text)
        self.assertEqual((self.turns, warned), ([], []))
        verbs = (self.fake / "calls").read_text().split()
        self.assertEqual((verbs[:3], verbs.count("run"), verbs[-1]),
                         (["probe", "known", "prepare"], 6, "finish"))
        with tarfile.open(self.fake / "parcel.tar") as tar:
            tar.extractall(self.fake / "parcel")
        heads = subprocess.run(["git", "bundle", "list-heads", "parcel/repo.bundle"], cwd=self.fake,
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(heads[1::2], ["HEAD", "refs/remotes/origin/main"])

    def test_what_the_helper_loses_or_fails_runs_here_on_a_turn(self):
        for codes, warn in (({2: helper.LOST}, []), ({2: 1}, ["WARN AK_SHARD=2/6"])):
            with self.subTest(codes=codes):
                text, warned = self.check(codes)
                self.assertIn("--- AK_SHARD=2/6 ---\n[exit 0]\npiece 2/6", text)
                self.assertIn("helper ran 1/6", text)
                self.assertNotIn("acme broke", text)
                self.assertEqual(len(self.turns), 1)
                self.assertEqual([line[:17] for line in warned], warn)

    def test_the_log_says_which_pieces_the_helper_lost_or_that_every_piece_passed_there(self):
        passed, lost = ("every piece passed on the suite helper acme-mac",
                        "the suite helper lost AK_SHARD=2/6; it runs here")
        for codes, said in (({}, [passed]), ({2: helper.LOST}, [lost]), ({2: 1}, []),
                            ({2: helper.SHORT}, [])):
            with self.subTest(codes=codes):
                self.check(codes)
                self.assertEqual([line for line in self.logs if line in (passed, lost)], said)

    def test_a_piece_failed_there_keeps_what_it_printed_there(self):
        warned = self.check({2: 1})[1]
        kept = re.fullmatch(r"WARN AK_SHARD=2/6 failed on the suite helper; "
                            r"what it printed there: (.+)", warned[0])
        self.assertEqual(Path(kept[1]).read_text(), "acme broke 2/6\n")

    def test_a_vm_that_ran_out_of_memory_runs_its_piece_here_and_the_next_vms_are_larger(self):
        text, warned = self.check({2: helper.SHORT})
        self.assertIn("--- AK_SHARD=2/6 ---\n[exit 0]\npiece 2/6", text)
        self.assertEqual((len(self.turns), warned), (1, []))
        # each VM had twice a piece's 410 MiB; the next ones each get twice as much
        self.assertEqual([path.read_text() for path in config.STATE.glob("helper-memory-*")],
                         ["1640\n"])
        self.check({})
        self.assertIn("suite on acme-mac: 3 pieces, 2 CPUs and 1640 MiB each", self.logs)

    def test_a_vm_that_ran_out_of_memory_counts_when_a_sibling_runs_out_of_time(self):
        ran, lock = [], threading.Lock()

        def limited(argv, _left, on_timeout, **_kw):
            # The first piece to start runs out of memory, whichever it is: a sibling's ceiling
            # cancels every piece not yet started, so a fixed piece may never run.
            with lock:
                ran.append(argv)
                if len(ran) == 1:
                    return helper.SHORT, "", False
            on_timeout("ceiling", 0)
            return worker.TIMEOUT, "", True
        with patch.object(helper, "piece", side_effect=lambda _away, shard, _command: [shard]), \
                patch.object(worker, "limited", side_effect=limited):
            gate.run_suite(SUITE, 30, cwd=self.repo, activity=self.root / "live.log",
                           output=io.BytesIO())
        self.assertEqual([path.read_text() for path in config.STATE.glob("helper-memory-*")],
                         ["1640\n"])

    def test_suites_that_ran_out_of_memory_at_once_never_lower_the_floor(self):
        away = helper.Away("acme-mac", "k", "acme", "img", 3, 2, 1000, "", "", "")
        read, newer = helper._least, threading.Thread(
            target=helper.short, args=(away._replace(memory_mb=2000),))

        def least(repo):
            # the larger suite's floor lands while the smaller one is between read and write
            floor = read(repo)
            if newer.ident is None:
                newer.start()
                newer.join(0.5)
            return floor
        with patch.object(helper, "_least", side_effect=least):
            helper.short(away)
            newer.join()
        self.assertEqual(read("acme"), 4000)

    def test_a_piece_that_changes_its_checkout_there_fails_there(self):
        (self.repo / "tracked").write_text("committed\n")
        subprocess.run([*self.git, "add", "tracked"], check=True)
        subprocess.run([*self.git, "commit", "-qm", "tracked"], check=True)
        warned = self.check({}, SUITE + "; echo altered >>tracked")[1]
        self.assertEqual(sorted(line[:17] for line in warned),
                         [f"WARN AK_SHARD={k}/6" for k in range(1, 7)])

    def test_a_repository_s_own_recipe_builds_its_own_image(self):
        def commit(files):
            for name, text in files.items():
                (self.repo / name).parent.mkdir(exist_ok=True)
                (self.repo / name).write_text(text)
            subprocess.run([*self.git, "add", *files], check=True)
            subprocess.run([*self.git, "commit", "-qm", "recipe"], check=True)
            text, warned = self.check({})
            if "helper ran" not in text:
                return warned
            with tarfile.open(self.fake / "parcel.tar") as tar:
                image = {member.name: (member.mode, tar.extractfile(member).read())
                         for member in tar if member.name.startswith(("image/", "context/"))}
            return (self.fake / "images").read_text().split()[-1], image

        # a repository with no recipe runs its suite here, asking the helper nothing
        subprocess.run([*self.git, "rm", "-q", helper.RECIPE], check=True)
        subprocess.run([*self.git, "commit", "-qm", "no recipe"], check=True)
        text, warned = self.check({})
        self.assertEqual(("helper ran" in text, warned), (False, []))
        self.assertFalse((self.fake / "calls").exists())
        # a copied file named as the recipe is sent beside it, and keeps its mode
        recipe = ("FROM acme/base\nCOPY --chown=ak requirements.txt \\\n  ci/pins.txt /tmp/\n"
                  "COPY Containerfile setup.sh /opt/\n")
        (self.repo / "setup.sh").touch(0o755)
        name, image = commit({"AGENTS.md": "---\nsuite_image: ci/suite.Containerfile\n---\n",
                              "ci/suite.Containerfile": recipe, "requirements.txt": "acme==1\n",
                              "ci/pins.txt": "pin\n", "Containerfile": "FROM acme/app\n",
                              "setup.sh": "true\n"})
        self.assertEqual(image, {"image/Containerfile": (0o644, recipe.encode()),
                                 "context/requirements.txt": (0o644, b"acme==1\n"),
                                 "context/ci/pins.txt": (0o644, b"pin\n"),
                                 "context/Containerfile": (0o644, b"FROM acme/app\n"),
                                 "context/setup.sh": (0o755, b"true\n")})
        self.assertRegex(name, r"^ak-helper-[0-9a-f]{12}:[0-9a-f]{12}$")
        # a changed copied file, or its mode, names a new image of the same repository
        changed = commit({"requirements.txt": "acme==2\n"})[0]
        (self.repo / "setup.sh").chmod(0o644)
        names = [name, changed, commit({"setup.sh": "true\n"})[0]]
        self.assertEqual((len({each.split(":")[0] for each in names}), len(set(names))), (1, 3))
        # what ak cannot send leaves the suite here
        (self.repo / "pins.link").symlink_to("ci/pins.txt")
        subprocess.run([*self.git, "add", "pins.link"], check=True)
        for line in ("COPY . /app", "ADD https://acme.test/x /x", "COPY *.txt /tmp/",
                     "COPY pins.link /tmp/"):
            with self.subTest(line=line):
                warned = commit({"ci/suite.Containerfile": f"FROM acme/base\n{line}\n"})
                self.assertEqual([line[:46] for line in warned],
                                 ["WARN the suite helper cannot build suite_image"])

    def test_no_helper_named_runs_here(self):
        for text in ("", 'suite_helper = "acme-mac\n'):
            with self.subTest(config=text):
                (config.HOME / config.CONFIG_NAME).write_text(text)
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
        self.repo = self.fake / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo))
        self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "start")
        self.git("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        for context in (patch.object(helper, "SSH", (str(self.fake / "ssh"),)), patch.dict(
                os.environ, {"PATH": f"{self.fake}:{os.environ['PATH']}", "HOME": str(self.fake),
                             "FAKE": str(self.fake), "FAKE_AC_CALLS": "99"})):
            context.start()
            self.addCleanup(context.stop)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=a@acme.test",
                               *args], capture_output=True, text=True, check=True).stdout.strip()

    def prepare(self, key, repo="acme", known=None):
        """`prepare` of the repository as `start` sends it, as `repo` there, after `known`'s
        answer (asked now when None): (its exit, the commits its bundle needs the Mac to have
        already, or None when it sends no bundle)."""
        known = helper._known("acme-mac", repo) if known is None else known
        recipe = {"image/Containerfile": (0o644, (helper.TOOLS / "Containerfile").read_bytes()),
                  "context/setup.sh": (0o755, b"true\n")}
        with tempfile.TemporaryFile() as parcel:
            helper._parcel(self.repo, "main", known, recipe, parcel)
            parcel.seek(0)
            with tarfile.open(fileobj=parcel) as tar:
                names = tar.getnames()
                header = (tar.extractfile("repo.bundle").read().split(b"\n\n")[0]
                          if "repo.bundle" in names else None)
            parcel.seek(0)
            code = helper._remote("acme-mac", "prepare", key, "ak-helper:new", repo,
                                  stdin=parcel).returncode
        needs = None if header is None else [line[1:].split()[0].decode()
                                             for line in header.splitlines() if line[:1] == b"-"]
        return code, needs

    def test_probe_leaves_load_half_the_free_memory_and_battery(self):
        # 10 CPUs less a load of 1; half of 8 GiB free; each VM twice its piece's memory
        self.assertEqual(helper.room("acme-mac", 1.0, 500), ((4, 2, 1000), ""))
        # a small piece still gets two CPUs: 9 spare make 4 VMs, not 9 of one CPU
        self.assertEqual(helper.room("acme-mac", 1.0, 100), ((4, 2, 200), ""))
        self.assertEqual(helper.room("acme-mac", 1.0, 2100),
                         (None, "has no room (9 spare CPUs and 4096 MiB)"))
        # VMs a suite of the repository ran out of memory in: fewer, larger ones
        self.assertEqual(helper.room("acme-mac", 1.0, 500, 1500), ((2, 4, 1500), ""))
        (self.fake / "system-broken").touch()
        self.assertEqual(helper._remote("acme-mac", "probe", text=True).returncode, helper.BROKEN)
        (self.fake / "system-broken").unlink()
        os.environ["FAKE_AC_CALLS"] = "0"
        self.assertEqual(helper.room("acme-mac", 1.0, 500), (None, "is on battery"))

    def test_mac_sh_alone_as_an_ak_updated_under_a_running_suite_sends_it_runs_the_mac(self):
        probe = subprocess.run([str(self.fake / "ssh"), "acme-mac", shlex.join(
            ["bash", "-c", (helper.TOOLS / "mac.sh").read_text(), "mac.sh", "probe"])],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout, "cpus 10\nload 1.00\nroom_mb 4096\n", probe.stderr)

    def test_suites_prepare_beside_one_another_and_only_their_own_old_image_goes(self):
        prepare = lambda key: self.prepare(key)[0]
        # a failed build keeps the helper's old image and drops the base it fetched
        (self.fake / "broken").touch()
        self.assertEqual(prepare("broken"), helper.BROKEN)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "docker.io/library/debian:trixie-slim\n")
        (self.fake / "broken").unlink()
        (self.fake / "deleted").unlink()
        self.assertEqual(prepare("first"), 0)
        self.assertEqual((self.root / "first/context/setup.sh").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "ak-helper:old\ndocker.io/library/debian:trixie-slim\n")
        self.assertEqual(prepare("second"), 0)
        for key in ("first", "second"):
            helper.finish(helper.Away("acme-mac", key, *[None] * 8))
        self.assertEqual(prepare("third"), 0)
        # a base the owner had before the build stays
        helper.finish(helper.Away("acme-mac", "third", *[None] * 8))
        (self.fake / "has-ak-helper:new").unlink()
        (self.fake / "has-debian:trixie-slim").touch()
        (self.fake / "deleted").unlink()
        self.assertEqual(prepare("fourth"), 0)
        self.assertEqual((self.fake / "deleted").read_text(), "ak-helper:old\n")

    def test_the_mac_keeps_no_build_cache_nor_an_old_image_once_no_suite_names_it(self):
        # a suite that never finished still names the old image as the new one is built
        (self.root / "dead/image").mkdir(parents=True)
        (self.root / "dead/image/name").write_text("ak-helper:old\n")
        self.assertEqual(self.prepare("first")[0], 0)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "docker.io/library/debian:trixie-slim\n")
        # its tree goes a day on, and the next prepare, which builds nothing, takes the image
        stale = time.time() - 3 * 86400
        os.utime(self.root / "dead", (stale, stale))
        self.assertEqual(self.prepare("second")[0], 0)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "docker.io/library/debian:trixie-slim\nak-helper:old\n")
        self.assertEqual((self.fake / "builder").read_text(), "stop\ndelete\ndelete\n")

    def test_an_image_a_listed_vm_may_use_stays(self):
        # `container ls` names an image with its registry; no listing could be any image
        (self.fake / "listed").write_text("vm registry.acme.test/library/ak-helper:old linux\n")
        self.assertEqual(self.prepare("listed")[0], 0)
        (self.fake / "has-ak-helper:new").unlink()
        (self.fake / "ls-broken").touch()
        self.assertEqual(self.prepare("unknown")[0], 0)
        self.assertEqual((self.fake / "deleted").read_text(),
                         "docker.io/library/debian:trixie-slim\n")

    def test_a_suite_sends_only_the_history_the_mac_lacks(self):
        (self.fake / "has-ak-helper:new").touch()
        mirror, other = self.root / "mirrors" / "acme", self.root / "mirrors" / "other"

        def suite(key, known=None):
            code, needs = self.prepare(key, known=known)
            helper.finish(helper.Away("acme-mac", key, *[None] * 8))
            self.assertEqual(code, 0)
            # it has the tree under test, and history up to the origin branch it compares against
            self.git("-C", str(mirror), "cat-file", "-e",
                     self.git("-C", str(self.repo), "rev-parse", "HEAD"))
            self.assertEqual(self.git("-C", str(mirror), "rev-parse", "refs/known/base"),
                             self.git("-C", str(self.repo), "rev-parse", "origin/main"))
            return needs

        start = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.assertEqual(suite("first"), [])          # the whole history
        self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "merged")
        self.git("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(suite("second"), [start])    # only the commit after what it has
        self.assertIsNone(suite("third"))              # nothing it lacks: no bundle
        # Another repository's history unused for a week goes, its image with it, at a third
        # one's suite; this one's stays from the moment a suite asks what it has.
        self.assertEqual(self.prepare("lost", "other")[0], 0)
        helper.finish(helper.Away("acme-mac", "lost", *[None] * 8))
        for path in (mirror, other):
            os.utime(path, (time.time() - 9 * 86400,) * 2)
        known = helper._known("acme-mac", "acme")
        self.assertEqual(self.prepare("between", "new")[0], 0)
        helper.finish(helper.Away("acme-mac", "between", *[None] * 8))
        self.assertIsNone(suite("fourth", known))
        self.assertEqual(sorted(path.name for path in mirror.parent.iterdir() if path.is_dir()),
                         ["acme", "new"])
        self.assertEqual((self.fake / "deleted").read_text(),
                         "ak-helper:old\nak-helper-other:old\n")
        # A suite's commits outlive a collection while it runs, though origin's branch left
        # them; once it finished, the next suite's collection drops them.
        tested = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.git("-C", str(self.repo), "checkout", "-q", "--orphan", "rewritten")
        self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "rewritten")
        self.git("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("-C", str(self.repo), "checkout", "-q", "--detach", tested)
        self.assertEqual(self.prepare("fifth")[0], 0)
        self.git("-C", str(mirror), "gc", "-q", "--prune=now")
        self.git("-C", str(mirror), "cat-file", "-e", tested)
        helper.finish(helper.Away("acme-mac", "fifth", *[None] * 8))
        self.git("-C", str(self.repo), "checkout", "-q", "rewritten")
        suite("sixth")
        self.git("-C", str(mirror), "gc", "-q", "--prune=now")
        self.assertNotEqual(subprocess.run(["git", "-C", str(mirror), "cat-file", "-e", tested],
                                           capture_output=True).returncode, 0)

    def test_a_suite_whose_history_there_went_since_known_sends_it_all(self):
        (self.repo / helper.RECIPE).parent.mkdir(parents=True)
        (self.repo / helper.RECIPE).write_text("FROM acme/base\n")
        self.git("-C", str(self.repo), "add", helper.RECIPE)
        self.git("-C", str(self.repo), "commit", "-q", "-m", "recipe")
        self.git("-C", str(self.repo), "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")
        known, logs = helper._known, []

        def gone(alias, repo):    # another suite deletes the copy once it has answered
            answer = known(alias, repo)
            shutil.rmtree(self.root / "mirrors" / repo, ignore_errors=True)
            return answer

        with patch.object(helper.config, "suite_helper", return_value="acme-mac"), \
                patch.object(helper, "room", return_value=((1, 2, 512), "")), \
                patch.object(helper.orch, "agent_programs", return_value=[]), \
                patch.object(helper, "_known", side_effect=gone):
            for _ in range(2):
                away, reason = helper.start(1, 512, self.repo, logs.append)
                self.assertIsNotNone(away, logs)
                self.assertEqual(reason, "")
                helper.finish(away)
                self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "merged")
                self.git("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")

    def test_a_vm_still_starting_or_up_after_its_charger_went_stops(self):
        for path in ("key", "mirrors/acme"):
            (self.root / path).mkdir(parents=True)
        (self.fake / "stalls").touch()
        os.environ["FAKE_AC_CALLS"] = "1"
        run = helper._remote("acme-mac", "run", "key", "ak-helper:new", "ak-key-1-2", 1, 512,
                             "acme", timeout=30)
        self.assertEqual(run.returncode, helper.BATTERY)
        self.assertEqual(list(self.fake.glob("vm-*")), [])


if __name__ == "__main__":
    unittest.main()

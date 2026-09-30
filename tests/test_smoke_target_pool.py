"""Check 4 takes a free smoke target, so suites never queue for one.

Offline and on fakes only.  Check 4 is lifted out of tests/smoke.sh with the pool code above it
and run as whole suites side by side: a `gh` that serves and creates bare repositories in a
temporary directory standing for the caller's account, an `ak` whose run holds its target until
this test lets it go, and lock files of this test's own.  The bound is the loop's own count,
read from a caller's HOME under the same temporary directory.  Nothing reaches GitHub, a model,
the host's locks or the host's config.
"""

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK4 = SMOKE[SMOKE.index("# --- 4: ak run end to end"):SMOKE.index("# --- 5: notify")]
LOCK_CODE = SMOKE[SMOKE.index("\nSMOKE_LOCK=") + 1:SMOKE.index("# The test hook")]
WAITING = "check 4: waiting for another suite's turn"

# $ACCOUNT holds the caller's repositories.  The run notes the target it was cloned from, then
# holds it -- and so its lock -- until the test writes `release` into the suite's WORK.
FAKES = r'''
skip_spent() { return 1; }
gh() {
  printf '%s\n' "$*" >>"$WORK/gh.log"
  case "$*" in
    'api user --jq .login') echo caller ;;
    'api --paginate user/repos?affiliation=owner&per_page=100 --jq .[].name')
      [ -z "${LISTING_FAILS:-}" ] || return 1
      ls "$ACCOUNT" | sed 's/\.git$//' ;;
    'repo view caller/'*) test -d "$ACCOUNT/${3#caller/}.git" ;;
    'repo create caller/'*' --private') git init -q --bare -b main "$ACCOUNT/${3#caller/}.git" ;;
    'repo clone caller/'*) git clone -q "$ACCOUNT/${3#caller/}.git" "$4" ;;
    *) echo "unexpected gh command: $*" >&2; return 97 ;;
  esac
}
ak() {
  if [ "$1 $2" = "run clean" ]; then rm -rf -- "$WORK/wt"; return 0; fi
  # renamed into place, so the test never reads a target half written
  basename "$(git remote get-url origin)" .git >"$WORK/target.part"
  mv "$WORK/target.part" "$WORK/target"
  until [ -e "$WORK/release" ]; do sleep .1; done
  local d="$HOME/.agentkit/runs/fake-run"
  mkdir -p -- "$d" "$WORK/wt"
  printf 'VERDICT: PASS\nmerged: yes\npr: https://example.invalid/pull/1\n' >"$d/result.md"
  printf '{"repo": "%s", "worktree": "%s"}\n' "$CLONE" "$WORK/wt" >"$d/run.json"
  printf '[12:00:01] round 1: PASS\n' >"$d/log.txt"
  echo "[12:00:00] run fake-run: $*"
}
'''


class TargetPool(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="smoke-target-pool-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.account = self.root / "account"
        self.caller = self.root / "caller"
        self.lock = self.root / "locks/remote.lock"
        repo = self.root / "repo"
        for path in (self.account, self.caller / ".agentkit/runs", self.lock.parent,
                     repo / "tests"):
            path.mkdir(parents=True)
        (repo / "tests/verify_delivery.py").write_text("")
        (repo / "agentkit").symlink_to(REPO / "agentkit")
        # a waiting suite lists the pool every second here, not every minute
        lock_code = LOCK_CODE.replace("\nSMOKE_LOCK_LIST=60 ", "\nSMOKE_LOCK_LIST=1 ")
        self.assertNotEqual(lock_code, LOCK_CODE)
        self.script = self.root / "suite.sh"
        self.script.write_text("\n".join(["set -uo pipefail", lock_code,
                                          f". {REPO}/tests/acceptance.sh", FAKES, CHECK4,
                                          "finish"]))
        self.env = {**os.environ, "REPO": str(repo), "ACCOUNT": str(self.account),
                    "SMOKE_CALLER_HOME": str(self.caller), "AK_SMOKE_LOCK": str(self.lock),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for name in ("AGENTKIT_RUN", "AK_RUN_ROLE", "AGENTKIT_SESSION", "AK_NOTIFY_SINK_LOG",
                     "AK_HOST_READINGS"):
            self.env.pop(name, None)

    def bound(self, count):
        """The caller pins the heavy suites the loop admits at once."""
        (self.caller / ".agentkit/config.toml").write_text(f"max_gates = {count}\n")

    def target_lock(self, n):
        return self.lock if n == 1 else self.lock.with_name(f"remote-{n}.lock")

    def existing(self, *names):
        for name in names:
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                            str(self.account / f"{name}.git")], check=True)

    def hold(self, n):
        """This test stands in for another suite holding target n."""
        fd = os.open(self.target_lock(n), os.O_RDONLY | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def suite(self, name, wait=60, **env):
        work = self.root / name
        (work / "home").mkdir(parents=True)
        with (work / "out").open("w") as out:
            proc = subprocess.Popen(["bash", str(self.script)], stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True,
                                    env={**self.env, "WORK": str(work), "HOME": str(work / "home"),
                                         "AK_SMOKE_LOCK_WAIT": str(wait), **env})

        def stop():
            (work / "release").touch()
            try:
                os.killpg(proc.pid, signal.SIGKILL)   # the suite, its run and its lock's holder
            except ProcessLookupError:
                pass
            proc.wait(timeout=30)

        self.addCleanup(stop)
        return proc, work

    def until(self, test, what, work, timeout=60):
        deadline = time.monotonic() + timeout
        while not test():
            if time.monotonic() > deadline:
                self.fail(f"never {what}:\n" + self.out(work))
            time.sleep(.1)

    def out(self, work):
        return (work / "out").read_text()

    def target(self, work):
        """The target the suite's run was cloned from, once it is running there."""
        self.until((work / "target").exists, "ran on a target", work)
        return (work / "target").read_text().strip()

    def finish(self, proc, work):
        (work / "release").touch()
        proc.wait(timeout=120)
        out = self.out(work)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("PASS  4 ak run: pr: https://example.invalid/pull/1 merged", out)
        return out

    def changed(self, work):
        """The gh calls that did more than ask what exists."""
        calls = (work / "gh.log").read_text().splitlines()
        return [c for c in calls if not c.startswith(("api ", "repo view"))]

    def seeded(self, name):
        return subprocess.run(["git", "--git-dir", str(self.account / f"{name}.git"), "show",
                               "main:tests/test_hello.py"], capture_output=True).returncode == 0

    def test_two_suites_at_once_take_two_different_targets(self):
        self.bound(2)
        suites = [self.suite("one"), self.suite("two")]
        # each run holds its target while the other is taken: two at once, never the same one
        self.assertEqual({self.target(work) for _, work in suites},
                         {"agentkit-smoke", "agentkit-smoke-2"})
        for proc, work in suites:
            self.assertNotIn(WAITING, self.finish(proc, work))
        for name in ("agentkit-smoke", "agentkit-smoke-2"):
            self.assertTrue(self.seeded(name), name)

    def test_a_suite_that_finds_every_target_busy_below_the_bound_creates_the_next(self):
        self.bound(3)
        self.existing("agentkit-smoke", "agentkit-smoke-2")
        self.hold(1)
        self.hold(2)
        proc, work = self.suite("third")
        self.assertEqual(self.target(work), "agentkit-smoke-3")
        out = self.finish(proc, work)
        self.assertNotIn(WAITING, out)
        self.assertEqual([c for c in self.changed(work) if c.startswith("repo create")],
                         ["repo create caller/agentkit-smoke-3 --private"])
        self.assertTrue(self.seeded("agentkit-smoke-3"))
        self.assertFalse(self.seeded("agentkit-smoke-2"))   # a busy target is never reset

    def test_at_the_bound_a_suite_waits_for_a_target_to_come_free(self):
        self.bound(2)
        self.existing("agentkit-smoke", "agentkit-smoke-2")
        self.hold(1)
        second = self.hold(2)
        self.target_lock(3).touch()   # a leftover lock file names no repository
        proc, work = self.suite("waiting")
        self.until(lambda: WAITING in self.out(work), "waited", work)
        time.sleep(1.5)
        # waiting, and it has touched no remote: nothing created or cloned
        self.assertIsNone(proc.poll(), self.out(work))
        self.assertEqual(self.changed(work), [], self.out(work))
        fcntl.flock(second, fcntl.LOCK_UN)
        self.assertEqual(self.target(work), "agentkit-smoke-2")
        self.finish(proc, work)
        self.assertNotIn("agentkit-smoke-3", "\n".join(self.changed(work)))

    def test_every_existing_target_is_taken_before_one_is_made(self):
        # a gap in the numbers, /tmp forgot the third target's lock file, and the bound fell
        # since it was made: the pool is what the account lists, and it never grows past two
        self.existing("agentkit-smoke", "agentkit-smoke-3")
        self.hold(1)
        for count in (1, 2):
            with self.subTest(bound=count):
                self.bound(count)
                proc, work = self.suite(f"bound-{count}")
                self.assertEqual(self.target(work), "agentkit-smoke-3")
                self.assertNotIn(WAITING, self.finish(proc, work))
                self.assertFalse([c for c in self.changed(work) if c.startswith("repo create")])

    def test_a_listing_that_failed_makes_no_target(self):
        # the reviewer's case: bound 2, the first and third targets exist, the first is held,
        # and the account cannot be listed. The suite takes no number it cannot see: it waits
        # for agentkit-smoke, and never makes agentkit-smoke-2 beside the free third.
        self.bound(2)
        self.existing("agentkit-smoke", "agentkit-smoke-3")
        first = self.hold(1)
        proc, work = self.suite("blind", LISTING_FAILS="1")
        self.until(lambda: WAITING in self.out(work), "waited", work)
        time.sleep(1.5)
        self.assertIsNone(proc.poll(), self.out(work))
        self.assertEqual(self.changed(work), [], self.out(work))
        fcntl.flock(first, fcntl.LOCK_UN)
        self.assertEqual(self.target(work), "agentkit-smoke")
        self.finish(proc, work)
        self.assertFalse([c for c in self.changed(work) if c.startswith("repo create")])

    def test_the_bound_is_read_again_at_every_try(self):
        # the reviewer's case: a bound that falls while a suite waits makes no target past it,
        # and one that rises lets the waiting suite make the next
        self.bound(2)
        self.existing("agentkit-smoke")
        first = self.hold(1)
        second = self.hold(2)
        proc, work = self.suite("falling")
        self.until(lambda: WAITING in self.out(work), "waited", work)
        self.bound(1)
        time.sleep(3.5)                        # three listings at the new bound
        fcntl.flock(second, fcntl.LOCK_UN)
        time.sleep(2.5)
        self.assertIsNone(proc.poll(), self.out(work))
        self.assertEqual(self.changed(work), [], self.out(work))
        fcntl.flock(first, fcntl.LOCK_UN)
        self.assertEqual(self.target(work), "agentkit-smoke")
        self.finish(proc, work)

    def test_a_rising_bound_lets_a_waiting_suite_make_the_next(self):
        self.bound(1)
        self.existing("agentkit-smoke")
        self.hold(1)
        proc, work = self.suite("rising")
        self.until(lambda: WAITING in self.out(work), "waited", work)
        self.bound(2)
        self.assertEqual(self.target(work), "agentkit-smoke-2")
        self.finish(proc, work)
        self.assertEqual([c for c in self.changed(work) if c.startswith("repo create")],
                         ["repo create caller/agentkit-smoke-2 --private"])

    def test_a_waiting_suite_takes_a_target_another_suite_added(self):
        # another suite, admitted at a larger bound, makes the second target while this one waits
        self.bound(1)
        self.existing("agentkit-smoke")
        self.hold(1)
        maker = self.hold(2)
        proc, work = self.suite("waiting")
        self.until(lambda: WAITING in self.out(work), "waited", work)
        self.existing("agentkit-smoke-2")
        fcntl.flock(maker, fcntl.LOCK_UN)
        self.assertEqual(self.target(work), "agentkit-smoke-2")
        self.finish(proc, work)
        self.assertFalse([c for c in self.changed(work) if c.startswith("repo create")])

    def test_a_killed_holder_frees_its_target(self):
        self.bound(1)
        first, first_work = self.suite("killed")
        self.assertEqual(self.target(first_work), "agentkit-smoke")
        second, second_work = self.suite("next")
        self.until(lambda: WAITING in self.out(second_work), "waited", second_work)
        # killed outright: no EXIT trap gives the target back, only its holder seeing it gone
        os.kill(first.pid, signal.SIGKILL)
        first.wait(timeout=30)
        self.assertEqual(self.target(second_work), "agentkit-smoke")
        self.finish(second, second_work)

    def test_the_bound_is_the_loop_s_own_count(self):
        def bound(**env):
            proc = subprocess.run(["bash", "-c", LOCK_CODE + "\nsmoke_pool_bound"],
                                  capture_output=True, text=True, timeout=60,
                                  env={**self.env, **env})
            return proc.stdout.strip()

        readings = json.dumps({"cpus": 4, "load": 0.5, "free_mb": 2000})
        # derived from the host's headroom: 3.5 idle cores fit 5, 2000 MB fit 4
        self.assertEqual(bound(AK_HOST_READINGS=readings), "4")
        self.bound(2)
        # turn files a busier hour opened are no admission: the loop enforces its limit now
        for slot in range(5):
            (self.caller / f".agentkit/runs/.heavy-{slot}.lock").touch()
        self.assertEqual(bound(), "2")
        self.bound(0)
        self.assertEqual(bound(), "0")   # no cap: a suite never waits for a target


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Suites run side by side: only check 4, which resets a smoke target, may wait for one.

Offline and on fakes only.  Check 4's own block is lifted out of tests/smoke.sh together with
the lock code above it and run between a stand-in check before it and one after, on a lock
file of this test's own: a `gh` that serves a bare repository, an `ak` that writes a passing
run and a delivery check that reads it.  The caller's config pins one heavy suite, so the pool
is that one target (tests/test_smoke_target_pool.py grows it).  Nothing reaches GitHub, a
model or the host's lock.
The last class renders the names two suites give their runs and seats, and compares them.
"""

import fcntl
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run

SMOKE = (REPO / "tests/smoke.sh").read_text()
E2E = (REPO / "tests/e2e-fresh.sh").read_text()
CHECK4 = SMOKE[SMOKE.index("# --- 4: ak run end to end"):SMOKE.index("# --- 5: notify")]
LOCK_CODE = SMOKE[SMOKE.index("\nSMOKE_LOCK=") + 1:SMOKE.index("# The test hook")]
WAITING = "check 4: waiting for another suite's turn"

# Stand-ins for what check 4 calls out to.  Each notes whether another process could take the
# lock at the moment it ran: `held` is the suite holding the remote.
FAKES = r'''
lockstate() {
  python3 - "$SMOKE_LOCK" "${1:-0}" <<'PY'
import fcntl, os, sys, time
fd, deadline = os.open(sys.argv[1], os.O_RDONLY), time.monotonic() + float(sys.argv[2])
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("free")
        break
    except OSError:
        if time.monotonic() >= deadline:
            print("held")
            break
        time.sleep(.1)
PY
}
skip_spent() { return 1; }
gh() {
  printf '%s\n' "$*" >>"$WORK/gh.log"
  case "$*" in
    'api user --jq .login') echo caller ;;
    'api --paginate user/repos?affiliation=owner&per_page=100 --jq .[].name') echo agentkit-smoke ;;
    "repo clone caller/agentkit-smoke "*)
      lockstate >"$WORK/lock-at-seed"; git clone -q "$ORIGIN" "$4" ;;
    *) echo "unexpected gh command: $*" >&2; return 97 ;;
  esac
}
ak() {
  if [ "$1 $2" = "run clean" ]; then rm -rf -- "$WORK/wt"; return 0; fi
  lockstate >"$WORK/lock-at-run"
  local d="$HOME/.agentkit/runs/fake-run"
  mkdir -p -- "$d" "$WORK/wt"
  printf 'VERDICT: PASS\nmerged: yes\npr: https://example.invalid/pull/1\n' >"$d/result.md"
  printf '{"repo": "%s", "worktree": "%s"}\n' "$CLONE" "$WORK/wt" >"$d/run.json"
  printf '[12:00:01] round 1: PASS\n' >"$d/log.txt"
  echo "[12:00:00] run fake-run: $*"
}
'''
DELIVERY = '''import fcntl, os, sys
fd = os.open(os.environ["AK_SMOKE_LOCK"], os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = "free"
except OSError:
    state = "held"
open(os.path.join(os.environ["WORK"], "lock-at-delivery"), "w").write(state + "\\n")
'''


class CheckFourAlone(unittest.TestCase):
    """The lock is check 4's, from the seed to the delivery, and no other check's."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="smoke-lock-scope-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.work = self.root / "work"
        self.lock = self.root / "remote.lock"
        repo = self.root / "repo"
        for path in (self.work, self.root / "home/.agentkit", repo / "tests"):
            path.mkdir(parents=True)
        (self.root / "home/.agentkit/config.toml").write_text("max_gates = 1\n")
        (repo / "agentkit").symlink_to(REPO / "agentkit")   # the bound is the loop's own count
        (repo / "tests/verify_delivery.py").write_text(DELIVERY)
        self.lock.touch(0o644)
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        script = "\n".join([
            "set -uo pipefail",
            LOCK_CODE,
            f". {REPO}/tests/acceptance.sh",
            FAKES,
            'ok "3 a check before check 4"',
            CHECK4,
            'lockstate 5 >"$WORK/lock-after"',
            'ok "5 a check after check 4"',
            "finish",
        ])
        self.script = self.root / "suite.sh"
        self.script.write_text(script)
        self.env = {**os.environ, "HOME": str(self.root / "home"), "WORK": str(self.work),
                    "REPO": str(repo), "ORIGIN": str(origin), "AK_SMOKE_LOCK": str(self.lock),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for name in ("AGENTKIT_RUN", "AK_RUN_ROLE", "AGENTKIT_SESSION", "AK_NOTIFY_SINK_LOG"):
            self.env.pop(name, None)

    def hold(self):
        """This test stands in for the other suite: it holds the remote until told to stop."""
        fd = os.open(self.lock, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def suite(self, wait):
        proc = subprocess.Popen(["bash", str(self.script)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                env={**self.env, "AK_SMOKE_LOCK_WAIT": str(wait)})
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        lines = queue.Queue()

        def pump():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        return proc, lines

    def read_until(self, lines, text, seen, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if line is None:
                break
            seen.append(line.rstrip("\n"))
            if text in line:
                return
        self.fail(f"never saw {text!r}:\n" + "\n".join(seen))

    def rest(self, proc, lines, seen):
        proc.wait(timeout=120)
        while (line := lines.get(timeout=30)) is not None:
            seen.append(line.rstrip("\n"))
        proc.stdout.close()
        return "\n".join(seen)

    def gh_calls(self):
        return (self.work / "gh.log").read_text().splitlines()

    def noted(self, name):
        path = self.work / name
        return path.read_text().strip() if path.exists() else None

    def test_check_4_waits_for_the_lock_while_the_checks_before_it_run(self):
        fd = self.hold()
        proc, lines = self.suite(60)
        seen = []
        self.read_until(lines, "PASS  3 a check before check 4", seen)
        self.read_until(lines, WAITING, seen)
        time.sleep(1.5)
        # waiting, and it has not touched the remote: it only asked what exists
        self.assertIsNone(proc.poll(), "\n".join(seen))
        self.assertEqual(self.gh_calls(), ["api user --jq .login",
                                           "api --paginate user/repos?affiliation=owner&per_page=100 --jq .[].name"],
                         "\n".join(seen))
        fcntl.flock(fd, fcntl.LOCK_UN)
        out = self.rest(proc, lines, seen)
        self.assertEqual(proc.returncode, 0, out)
        for check in ("4 ak run: pr: https://example.invalid/pull/1 merged", "4b ak run clean",
                      "4c ak run", "4d no dead orchestrator seat", "5 a check after check 4"):
            self.assertIn(f"PASS  {check}", out)
        # held from the seed through the delivery, and given back before the next check
        self.assertEqual([self.noted(name) for name in
                          ("lock-at-seed", "lock-at-run", "lock-at-delivery", "lock-after")],
                         ["held", "held", "held", "free"], out)

    def test_a_suite_whose_wait_expires_fails_4_skips_4b_to_4d_and_runs_the_rest(self):
        self.hold()
        proc, lines = self.suite(1)
        out = self.rest(proc, lines, [])
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn("PASS  3 a check before check 4", out)
        self.assertIn("FAIL  4 ak run: every smoke target is still another suite's after 1s", out)
        for check in ("4b", "4c", "4d"):
            self.assertIn(f"SKIP  {check}: prerequisite run did not happen", out)
        self.assertIn("PASS  5 a check after check 4", out)
        self.assertIn("1 failed", out)
        # the remote was never touched: it only asked what exists
        self.assertFalse([c for c in self.gh_calls() if not c.startswith("api ")], out)
        self.assertIsNone(self.noted("lock-at-run"), out)

    def test_no_other_check_takes_the_lock(self):
        takes = [m.start() for m in re.finditer(r"^[^#\n]*\bsmoke_lock_hold\b(?!\(\))", SMOKE, re.M)]
        start = SMOKE.index(CHECK4)
        self.assertTrue(takes)
        for at in takes:
            self.assertTrue(start <= at < start + len(CHECK4),
                            SMOKE[SMOKE.rfind("\n", 0, at) + 1:SMOKE.find("\n", at)])

    def test_the_e2e_gate_locks_a_file_of_its_own(self):
        smoke, e2e = (re.search(r"^SMOKE_LOCK=\S*?(/tmp/[\w.-]+)\}?$", text, re.M).group(1)
                      for text in (SMOKE, E2E))
        self.assertEqual(smoke, "/tmp/agentkit-smoke-remote.lock")
        self.assertEqual(e2e, "/tmp/agentkit-e2e-remote.lock")


class TwoSuitesApart(unittest.TestCase):
    """Two suites started in the same minute give their runs and seats different names."""

    # Every task file the suite writes, and every fixed seat name made of the suite's pid --
    # with the repository name a review run's id is made of.
    TASKS = re.findall(r'^cat >"\$WORK/[\w.-]+\.md" <<\'?MD\'?\n---\n.*?\nMD\n', SMOKE, re.M | re.S)
    SEATS = re.findall(r'\b\w+="?((?:smoke|stall)[\w-]*-\$\$)', SMOKE)

    def suites(self):
        """What two suites started together make of those lines, each in a shell of its own."""
        procs = []
        for _ in range(2):
            work = tempfile.TemporaryDirectory(prefix="smoke-names-")
            self.addCleanup(work.cleanup)
            script = "R=/r; TR=/tr\n" + "".join(self.TASKS) + "echo $$ " + " ".join(self.SEATS)
            procs.append((Path(work.name), subprocess.Popen(
                ["bash", "-c", script], env={**os.environ, "WORK": work.name},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
        return [(work, *proc.communicate(timeout=30)) for work, proc in procs]

    def names(self, work, out):
        """Every run id and fixed seat name one suite gives, all in the same minute."""
        pid, *seats = out.split()
        found = set(seats)
        for task in sorted(work.glob("*.md")):
            title = re.search(r"^# (.+)$", task.read_text(), re.M).group(1)
            # the pid has to survive the slug's cut to 40 characters, the widest one included
            for token in (pid, "4194304"):
                self.assertTrue(run.slugify(title.replace(pid, token)).endswith("-" + token),
                                (task.name, title))
            found.add(f"20260930-1200-{run.slugify(title)}")
        return pid, found

    def test_two_suites_started_together_name_nothing_alike(self):
        self.assertGreaterEqual(len(self.TASKS), 7)
        (work1, out1, err1), (work2, out2, err2) = self.suites()
        self.assertEqual(err1 + err2, "")
        first, ours = self.names(work1, out1)
        second, theirs = self.names(work2, out2)
        self.assertNotEqual(first, second)
        self.assertEqual(len(ours), len(self.TASKS) + len(self.SEATS))
        self.assertEqual(ours & theirs, set())
        for seat in ("smoke-slice-", "smoke-ov-1-", "smoke-ov-2-", "smoke-inbox-",
                     "stall-claude-", "smokerepo-"):
            self.assertIn(seat + first, ours)


if __name__ == "__main__":
    unittest.main(verbosity=2)

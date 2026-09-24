"""An expired login is recognised at once, told once, and everything resumes by itself.

The night this closes: a Claude OAuth token expired around 01:00, every headless turn came
back with no events and an empty stderr, the loop read each one as a transport death, waited
twenty minutes, killed it and tried twice more -- an hour a run, three runs in `error`, which
`ak run resume` refuses -- while the seat flapped between `needs login` and `moving again` as
queued input redrew its screen.

Offline throughout: a temporary HOME, fake adapters written per test, and no real token, no
real `~/.claude` or `~/.codex`, and no model call anywhere.
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SLEEP = time.sleep                  # the real one, kept where a fixture needs to wait
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, terminal, usage, watch, worker

# A fake harness, in the two shapes a turn can take: one that authenticates and answers, and
# one whose token is gone -- no events, empty stderr, over in a moment, which is exactly what
# the real one did all night.
ADAPTER = r'''#!/usr/bin/env bash
set -uo pipefail
S=__STATE__
case "${1:-}" in
auth)
  if [ -s "$S/logged-out" ]; then
    echo "__H__: the token expired; run /login" >&2; exit 1
  fi
  echo "__H__: the token is still valid"; exit 0 ;;
run)
  out=$6
  mkdir -p -- "$out"
  printf '%s\n' "$2" >>"$S/turns"
  if [ -s "$S/stderr-says" ]; then
    : >"$out/events.jsonl"; cat "$S/stderr-says" >"$out/stderr.log"
    : >"$out/final.md"; : >"$out/session_id"; exit 1
  fi
  if [ -s "$S/logged-out" ]; then
    # what the harness actually did: nothing at all, and quickly
    : >"$out/events.jsonl"; : >"$out/stderr.log"; : >"$out/final.md"; : >"$out/session_id"
    exit 1
  fi
  printf '{"type":"thread.started","thread_id":"sid-__H__"}\n' >"$out/events.jsonl"
  printf 'sid-__H__\n' >"$out/session_id"
  printf 'fake __H__ adapter\n' >"$out/stderr.log"
  if grep -q '^You are the reviewer' "$5"; then
    printf 'VERDICT: PASS\n\n## Findings\n- none\n' >"$out/final.md"; exit 0
  fi
  printf 'hello\n' >"$4/work.txt"
  # only ever this workspace's own repository: a `git add` in a directory that is not one
  # walks up and stages the checkout the suite is running inside
  [ -d "$4/.git" ] && { git -C "$4" add -A >/dev/null 2>&1
                        git -C "$4" commit -qm work >/dev/null 2>&1; }
  printf '## Summary\nwrote work.txt\n' >"$out/final.md"; exit 0 ;;
usage)
  printf '{"provider":"test","meters":[],"error":null}\n' ;;
*)
  echo "fake adapter: no ${1:-}" >&2; exit 2 ;;
esac
'''

# ... and one whose token expires under the turn it is running: the launch authenticates, the
# turn produces nothing at all, and the verb answers differently once it has.
EXPIRING = r"""#!/usr/bin/env bash
set -uo pipefail
S=__STATE__
case "${1:-}" in
auth)
  [ -s "$S/logged-out" ] || { echo "__H__: the token is still valid"; exit 0; }
  echo "__H__: the token expired; run /login" >&2; exit 1 ;;
run)
  out=$6
  mkdir -p -- "$out"
  printf '%s\n' "$2" >>"$S/turns"
  echo yes >"$S/logged-out"
  : >"$out/events.jsonl"; : >"$out/stderr.log"; : >"$out/final.md"; : >"$out/session_id"
  exit 1 ;;
usage) printf '{"provider":"test","meters":[],"error":null}\n' ;;
*) echo "fake adapter: no ${1:-}" >&2; exit 2 ;;
esac
"""


# ... and one that says it is logged out and then never finishes: it keeps emitting events,
# so the silence window never closes and nothing but the line it already wrote can end it.
HANGING = r"""#!/usr/bin/env bash
set -uo pipefail
S=__STATE__
case "${1:-}" in
auth) echo "__H__: the token is still valid"; exit 0 ;;
run)
  out=$6
  mkdir -p -- "$out"
  printf '%s\n' "$2" >>"$S/turns"
  : >"$out/events.jsonl"; : >"$out/final.md"; : >"$out/session_id"
  printf 'Error: __MARK__\n' >"$out/stderr.log"
  while :; do printf '{"type":"tick"}\n' >>"$out/events.jsonl"; sleep 0.2; done ;;
usage) printf '{"provider":"test","meters":[],"error":null}\n' ;;
*) echo "fake adapter: no ${1:-}" >&2; exit 2 ;;
esac
"""


# A transport death is the other thing an empty turn can be, and it keeps the old road.
# One that dies twice on the provider before doing the work: the outage the loop
# resumes through, on the same session, rather than parking on any login.
FLAKY = r'''#!/usr/bin/env bash
set -uo pipefail
S=__STATE__
case "${1:-}" in
auth) echo "__H__: the token is still valid"; exit 0 ;;
run)
  out=$6
  mkdir -p -- "$out"
  n=$(($(cat "$S/flaky-n" 2>/dev/null || echo 0) + 1)); printf '%s\n' "$n" >"$S/flaky-n"
  printf '%s\n' run >>"$S/turns"
  if [ "$n" -le 2 ]; then
    : >"$out/events.jsonl"; : >"$out/session_id"
    printf 'API Error: 500\n' >"$out/stderr.log"
    : >"$out/final.md"
    exit 1
  fi
  printf '{"type":"thread.started","thread_id":"sid-__H__"}\n' >"$out/events.jsonl"
  printf 'sid-__H__\n' >"$out/session_id"
  printf 'fake __H__ adapter\n' >"$out/stderr.log"
  if grep -q '^You are the reviewer' "$5"; then
    printf 'VERDICT: PASS\n\n## Findings\n- none\n' >"$out/final.md"; exit 0
  fi
  printf 'hello\n' >"$4/work.txt"
  [ -d "$4/.git" ] && { git -C "$4" add -A >/dev/null 2>&1
                        git -C "$4" commit -qm work >/dev/null 2>&1; }
  printf '## Summary\nwrote work.txt\n' >"$out/final.md"; exit 0 ;;
usage) printf '{"provider":"test","meters":[],"error":null}\n' ;;
*) echo "fake adapter: no ${1:-}" >&2; exit 2 ;;
esac
'''


class Login(unittest.TestCase):
    """One HOME, fake adapters, a real git repository, and nothing that can reach a network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".login-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off", "NO_COLOR": "1",
            "AGENTKIT_UNATTENDED": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1"}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        self.harnesses = {m["harness"] for m in self.cfg["models"].values()}
        for harness in self.harnesses:
            self.adapter(harness, ADAPTER)
        self.stack.enter_context(patch.dict(os.environ,
                                            {config.ADAPTER_DIR_ENV: str(self.adapters)}))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(usage, "pick_order",
                                              return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(run, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "schedule_gc"))
        self.sleep = self.stack.enter_context(patch.object(run.time, "sleep"))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))

    # --- the fixture ---------------------------------------------------------

    def adapter(self, harness, text):
        path = self.adapters / f"{harness}.sh"
        path.write_text(text.replace("__STATE__", str(self.fixture)).replace("__H__", harness))
        path.chmod(0o755)
        return path

    def log_out(self, out=True):
        """Flip every fake harness's token, the way an expiry at 01:00 does."""
        (self.fixture / "logged-out").write_text("yes\n" if out else "")

    def turns(self):
        path = self.fixture / "turns"
        return path.read_text().splitlines() if path.exists() else []

    def sealed(self):
        """A PATH whose `security` can never reach the account's own Keychain.

        The temporary HOME hides `~/.claude`, but macOS keeps the seat's credentials in the
        Keychain, which no HOME hides: `security find-generic-password` would read the real
        one.  Every check that runs a shipped adapter runs it on this PATH, so the only
        credentials any of them can see are the ones the check itself wrote.
        """
        path = self.root / "sealed-bin"
        if not path.exists():
            path.mkdir()
            (path / "security").write_text(
                '#!/usr/bin/env bash\necho "security: no keychain in this fixture" >&2\nexit 1\n')
            (path / "security").chmod(0o755)
        return {"PATH": f"{path}:{os.environ['PATH']}"}

    def adopted(self, run_dir, argv, expected=None):
        """What `spawn_bg` leaves on disk: the receipt queued for the child it started."""
        state = run.read_state(run_dir)
        run.save_state(run_dir, {**state, "state": "queued", "slot_waiting": True,
                                 "resume_from": state["state"]})
        return 0

    def backoffs(self):
        """The transient waits, out of every sleep the process made.

        `run.time` is the one `time` module, so a `subprocess` waiting on a child polls
        through the same patched `sleep` with a few milliseconds of its own.  Those are
        not a wait, and only the transient delays are being counted here.
        """
        return [call.args[0] for call in self.sleep.call_args_list
                if call.args and call.args[0] in run.TRANSIENT_BACKOFF]

    def repo(self):
        work = self.root / "repo"
        run.git(self.root, "init", "--initial-branch=main", str(work))
        run.git(work, "config", "user.name", "fixture")
        run.git(work, "config", "user.email", "fixture@localhost")
        (work / "README.md").write_text("fixture\n")
        run.git(work, "add", ".")
        run.git(work, "commit", "-m", "base")
        self.work = work
        return work

    def task(self):
        path = self.root / "task.md"
        path.write_text(f"---\nrepo: {self.work}\nbase: main\nrounds: 1\n---\n"
                        "# Login fixture\n\n## Goal\nWrite work.txt.\n\n"
                        "## Done when\n```bash\ntest -f work.txt\n```\n")
        return path

    def launch(self):
        self.repo()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = run.main([str(self.task()), "--exec", "opus", "--review", "astra",
                             "--no-merge"])
        directory = max(run.run_dirs(), key=lambda d: d.name)
        return code, directory, run.read_state(directory)

    # --- 1: a turn that cannot authenticate ends at once ---------------------

    def test_an_empty_turn_with_a_failing_auth_verb_ends_the_turn_at_once(self):
        # No events, empty stderr, over in a moment: the shape the loop used to wait twenty
        # minutes on.  The `auth` verb is asked and the turn stops on the answer.
        self.log_out()
        directory = self.root / "out"
        began = time.monotonic()
        with self.assertRaises(worker.LoginExpired) as caught:
            worker.call(self.cfg, "opus", "do the thing", self.root, directory)
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(caught.exception.harness, "claude")
        self.assertIn("the token expired", caught.exception.why)
        # the verb refused before the launch, so no turn was ever started
        self.assertEqual(self.turns(), [])
        self.assertEqual(self.backoffs(), [])

    def test_a_stderr_auth_signature_ends_the_turn_at_once(self):
        # The token is fine as far as the verb can see; the harness says otherwise in its own
        # diagnostics, in the same words the babysitter reads off a seat's screen.
        mark = watch.auth_expiry("claude")[2][0]
        (self.fixture / "stderr-says").write_text(f"Error: {mark}\n")
        directory = self.root / "out"
        with self.assertRaises(worker.LoginExpired) as caught:
            worker.call(self.cfg, "opus", "do the thing", self.root, directory)
        self.assertEqual(caught.exception.harness, "claude")
        self.assertEqual(caught.exception.why, mark)
        self.assertEqual(len(self.turns()), 1)      # the turn ran, and stopped on what it said
        self.assertEqual(self.backoffs(), [])

    def test_a_stderr_signature_is_found_however_much_the_harness_said_after_it(self):
        # A harness that said it was logged out and then printed a page of its own unwinding
        # must not hide the one line that explains the turn: the whole log is read, not its
        # tail, and a signature astride a read boundary is still a signature.
        mark = watch.auth_expiry("claude")[2][0]
        for pad in (f"Error: {mark}\n" + "noise\n" * 40000,
                    "x" * (worker.STDERR_CHUNK - len(mark) // 2) + mark + "\ntrailing\n"):
            with self.subTest(length=len(pad)):
                (self.fixture / "stderr-says").write_text(pad)
                with self.assertRaises(worker.LoginExpired) as caught:
                    worker.call(self.cfg, "opus", "do it", self.root, self.root / "far-out")
                self.assertEqual(caught.exception.why, mark)

    def test_a_harness_that_says_it_and_then_never_stops_is_ended_on_that_line(self):
        # Its `auth` verb passes and its event stream never goes quiet, so neither the verb
        # nor the silence window can end this turn: the line it already wrote has to, while
        # it is still running.  Twenty minutes of a harness ticking away after saying it is
        # logged out is the whole of what this closes.
        mark = watch.auth_expiry("claude")[2][0]
        for harness in self.harnesses:
            self.adapter(harness, HANGING.replace("__MARK__", mark))
        began = time.monotonic()
        with self.assertRaises(worker.LoginExpired) as caught:
            worker.call(self.cfg, "opus", "do it", self.root, self.root / "hanging",
                        limit=20 * 60)
        spent = time.monotonic() - began
        self.assertEqual(caught.exception.why, mark)
        self.assertLess(spent, 30, f"took {spent:.0f}s; the silence window is 20 minutes")
        # and nothing it spawned outlived it: the adapter's own loop is gone with its group
        SLEEP(0.5)
        self.assertEqual(subprocess.run(["pgrep", "-f", str(self.adapters / "claude.sh")],
                                        capture_output=True).returncode, 1)

    def test_a_token_that_expires_mid_turn_is_caught_when_that_turn_says_nothing(self):
        # The night itself: the launch authenticated, the token expired under it, and the turn
        # came back with no events and an empty stderr.  That is not a transport death -- the
        # verb is asked again the moment such a turn ends, and it answers.
        for harness in self.harnesses:
            self.adapter(harness, EXPIRING)
        code, directory, state = self.launch()
        self.assertEqual(len(self.turns()), 1)          # one turn, not three
        self.assertEqual(self.backoffs(), [])           # and no twenty-minute ladder
        self.assertEqual((state["state"], state["waiting_for"]), ("waiting_login", "claude"))
        self.assertEqual(code, 1)

    def test_a_real_transport_death_is_resumed_with_growing_waits(self):
        # Empty turns whose harness can authenticate are what they always were: deaths on
        # the provider, resumed on the same session with the growing waits, and nothing
        # parked on a login.  The executor dies twice before doing the work; the reviewer
        # answers first time.
        self.adapter("claude", FLAKY)
        code, directory, state = self.launch()
        self.assertEqual(len(self.turns()), 4)
        self.assertEqual(self.backoffs(), [60, 300])
        self.assertEqual(state["state"], "pass")
        self.assertNotIn("waiting_for", state)
        self.assertEqual(code, 0)

    # --- 2: the run waits rather than dying ----------------------------------

    def test_the_run_parks_waiting_login_naming_the_harness(self):
        self.log_out()
        code, directory, state = self.launch()
        self.assertEqual(state["state"], "waiting_login")
        self.assertEqual(state["waiting_for"], "claude")
        self.assertIn("claude login expired", state["error"])
        self.assertEqual(code, 1)
        # no transport ladder was spent on it, and no window was waited out
        self.assertEqual(self.turns(), [])
        self.assertEqual(self.backoffs(), [])
        # it resumes itself, so nobody is told and no row offers its number -- and the state
        # column says what it waits for, under the open circle that means nobody must act
        self.assertTrue(run.needs_recovery(state))
        self.assertEqual(menu.run_state_word(state), "waiting for claude login")
        self.assertEqual(run.waiting_word(state), "waiting for claude login")
        self.assertEqual(run.waiting(state), "waiting for claude login")
        self.assertEqual(terminal.state_text(menu.run_state_word(state)),
                         "\u25cb waiting for claude login")
        with redirect_stdout(io.StringIO()) as out:
            run.cmd_status([])
        self.assertIn("\u25cb waiting for claude login", out.getvalue())
        with redirect_stdout(io.StringIO()) as plain:
            run.cmd_status(["--plain"])
        self.assertIn("waiting for claude login", plain.getvalue())
        self.assertNotIn("offers resume", out.getvalue())

    def test_a_job_leaves_a_parked_run_to_the_tick_instead_of_resuming_it(self):
        # Nothing in a job can log anybody in: a resume from the scheduler's thread would
        # park the run again before it reached a model and spend a launch every pass.
        self.log_out()
        _, directory, _ = self.launch()
        job_dir = config.HOME / "jobs" / "job-1"
        job_dir.mkdir(parents=True)
        task = {"name": "one", "state": "running", "run_id": directory.name}
        job = {"job_id": "job-1", "tasks": [task]}
        run.save_job(job_dir, job)
        logs, lock = [], threading.Lock()
        with patch.object(run, "cmd_resume", side_effect=AssertionError("resumed")):
            run.job_adopt_worker(self.cfg, job_dir, job, task, directory, lock, logs.append)
        self.assertEqual(task["state"], "queued")           # waiting beside the run
        self.assertTrue(task.get("budget_wait"))
        self.assertGreater(task["retry_after"], time.time())
        self.assertEqual(run.read_state(directory)["state"], "waiting_login")
        self.assertTrue(any("waiting for budget" in line for line in logs), logs)

    def test_every_job_attempt_waits_on_a_parked_login_instead_of_failing_the_task(self):
        # The four places a job hands an attempt back -- the one it was given, the delivery
        # retry, the one resume it is allowed and the one rerun on the next executor -- all
        # read the same answer: nothing here can log anybody in, so the task waits beside
        # the run rather than failing and taking its `after:` dependants down with it.
        self.log_out()
        _, directory, parked = self.launch()
        job_dir = config.HOME / "jobs" / "job-2"
        job_dir.mkdir(parents=True)
        for where in ("mid-run", "on delivery", "on resume", "on rerun"):
            with self.subTest(where=where):
                task = {"name": "one", "state": "running", "run_id": directory.name}
                job = {"job_id": "job-2", "tasks": [task]}
                run.save_job(job_dir, job)
                logs, lock = [], threading.Lock()
                self.assertTrue(run.job_wait_login(job_dir, job, task, logs.append, lock,
                                                   parked, where))
                self.assertEqual(task["state"], "queued")
                self.assertTrue(task["budget_wait"])
                self.assertGreater(task["retry_after"], time.time())
                self.assertIn(where, " ".join(logs))
        # ... and anything else is none of its business
        task = {"name": "one", "state": "running"}
        self.assertFalse(run.job_wait_login(job_dir, {"tasks": [task]}, task, print,
                                            threading.Lock(), {"state": "fail"}, "mid-run"))
        self.assertEqual(task["state"], "running")

    def test_a_login_expiring_on_the_delivery_retry_waits_instead_of_failing_the_task(self):
        # A task that PASSed but could not deliver is finished by the job itself with
        # `ak run merge`, and that command can hit an expired login like any other turn.
        # The ladder has to ask before it calls the delivery failed: the tick will resume
        # the run, and a task already marked failed has skipped its dependants by then.
        _, directory, state = self.launch()
        delivered = {**state, "state": "pass", "verdict": "PASS", "no_merge": False,
                     "merged": False, "merge_failed": True, "pr": None,
                     "merge_note": "delivery did not finish"}
        run.save_state(directory, delivered)
        job_dir = config.HOME / "jobs" / "job-3"
        job_dir.mkdir(parents=True)
        task = {"name": "one", "state": "running", "run_id": directory.name}
        job = {"job_id": "job-3", "tasks": [task]}
        run.save_job(job_dir, job)

        def park(argv):
            """what `ak run merge` leaves behind when a fixer turn cannot authenticate"""
            run.save_state(directory, {**delivered, "state": "waiting_login",
                                       "waiting_for": "claude",
                                       "error": "claude login expired: the token expired"})
            return 1

        logs, lock = [], threading.Lock()
        with patch.object(run, "cmd_merge", side_effect=park):
            run.job_ladder(self.cfg, job_dir, job, task, directory, delivered, 1,
                           logs.append, lock)
        self.assertEqual(task["state"], "queued")       # waiting, never failed
        self.assertTrue(task["budget_wait"])
        self.assertGreater(task["retry_after"], time.time())
        self.assertNotIn("verdict_line", {k: v for k, v in task.items() if "fail" in str(v)})
        self.assertIn("on delivery", " ".join(logs))
        self.assertEqual(run.read_state(directory)["state"], "waiting_login")

    def test_a_login_expiring_during_delivery_parks_the_run_it_was_merging(self):
        # A conflict fixer's turn inside `ak run merge` can hit an expired login like any
        # other turn: the receipt must not be left saying `running` with a live pid on it.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {
            **state, "state": "pass", "verdict": "PASS", "pr": None, "merged": False,
            "merge_failed": True, "merge_note": "delivery did not finish",
            "review": {"executor": "opus", "executor_provider": "anthropic",
                       "reviewer": "astra", "reviewer_provider": "openai",
                       "returncode": 0, "verdict": "PASS", "done_when": True,
                       **run.commit_identity(Path(state["worktree"]))},
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": "done"}]})
        expired = worker.LoginExpired("claude", "the token expired; run /login")
        with patch.object(run, "merge", side_effect=expired), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = run.cmd_merge([directory.name])
        after = run.read_state(directory)
        self.assertEqual((after["state"], after["waiting_for"]), ("waiting_login", "claude"))
        self.assertIn("claude login expired", after["error"])
        self.assertEqual(code, 1)
        self.assertTrue(run.needs_recovery(after))

    def test_the_tick_resumes_the_parked_run_when_the_auth_verb_passes(self):
        self.log_out()
        _, directory, state = self.launch()
        self.assertEqual(state["state"], "waiting_login")
        logs = []
        # still logged out: the tick leaves it exactly where it is, and says nothing
        watch.resume_waiting_login(log=logs.append)
        self.assertEqual(run.read_state(directory)["state"], "waiting_login")
        self.assertEqual(logs, [])
        self.log_out(False)
        launched = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, argv, expected=None:
                          launched.append((d.name, argv)) or 0):
            watch.resume_waiting_login(log=logs.append)
        self.assertEqual(launched, [(directory.name, ["resume", directory.name])])
        self.assertEqual(logs, [f"resumed {directory.name}: the claude login is back"])
        # and the resume is the one the command runs, on the work it left behind
        worktree, branch = state["worktree"], state["branch"]
        self.assertTrue(Path(worktree).is_dir())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = run.cmd_resume([directory.name])
        self.assertEqual(code, 0)
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertEqual((state["worktree"], state["branch"]), (worktree, branch))
        # nothing of the wait outlives it
        self.assertNotIn("waiting_for", state)
        self.assertNotIn("login_resume_at", state)

    def test_a_throttled_resume_is_tried_again_and_a_lost_worktree_becomes_an_interruption(self):
        self.log_out()
        _, directory, _ = self.launch()
        self.log_out(False)
        logs = []
        with patch.object(run, "spawn_bg", return_value=0):
            watch.resume_waiting_login(log=logs.append)
        # the launch is on its way; a second pass inside the window does not start another
        with patch.object(run, "spawn_bg", side_effect=AssertionError("relaunched")):
            watch.resume_waiting_login(log=logs.append)
        self.assertEqual(len(logs), 1)
        # A worktree that is gone, with the login back: this run waits for no login any more,
        # and saying it does would send him to `/login` for something he already has.  It is
        # an interruption, which names its own reason and offers its own number.
        state = run.read_state(directory)
        state.pop("login_resume_at")
        state.pop("login_back_at", None)
        state["worktree"] = str(self.root / "nowhere")
        run.save_state(directory, state)
        watch.resume_waiting_login(log=logs.append)
        after = run.read_state(directory)
        self.assertEqual(after["state"], "interrupted")
        self.assertIn("worktree", after["interruption_reason"])
        self.assertIn("login is back", after["interruption_reason"])
        self.assertTrue(after["recovery_pending"])
        self.assertNotIn("waiting_for", after)          # it names no login, because none is out
        self.assertNotIn("login", run.waiting_word(after))
        warnings = [line for line in logs if line.startswith("WARN")]
        self.assertEqual(len(warnings), 1)
        self.assertIn("worktree", warnings[0])
        # ... and a later pass finds nothing parked to look at
        watch.resume_waiting_login(log=logs.append)
        self.assertEqual(len([line for line in logs if line.startswith("WARN")]), 1)

    def test_a_login_that_goes_out_again_is_told_again_and_never_reads_as_resuming(self):
        # The tick found the login back, the launch did not get away, and then the login went
        # out again.  The mark that said `back` has to come off with it: otherwise the run
        # reads `waiting to resume` for ever, its seat reads `working`, and the second outage
        # is the one nobody is ever told about.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        seat = {"name": "atoll", "exited": False, "legacy": False}

        def tick(logs):
            """One whole pass: the seats, then the runs the login may have freed."""
            with patch.object(orch, "sessions", return_value=[seat]), \
                    patch.object(orch, "listing", return_value=[seat]), \
                    patch.object(orch, "tmux_out", return_value=(0, "")), \
                    patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                    patch.object(watch, "pane_text", return_value="$ "), \
                    patch.object(notify, "progress", return_value=False), \
                    patch.object(watch, "type_into", return_value=True):
                data = watch.load_state()
                watch.health(self.cfg, data, False, logs.append)
                watch.save_state(data)
            with patch.object(run, "spawn_bg", side_effect=config.Error("cannot fork")):
                watch.resume_waiting_login(log=logs.append)
            return watch.session_state("atoll", session=seat, cfg=self.cfg)

        with patch.object(notify, "shaped", wraps=notify.shaped) as card:
            logs = []
            blocked = tick(logs)                                   # out: told once
            self.assertEqual(blocked["word"], "needs you")
            self.assertIn("claude login expired", blocked["reason"])
            self.assertEqual(card.call_count, 1)

            self.log_out(False)
            back = tick(logs)                                      # back, but the launch failed
            self.assertEqual(back["word"], "working")
            self.assertTrue(run.read_state(directory)["login_back_at"])
            self.assertEqual(run.waiting_word(run.read_state(directory)), "waiting to resume")
            # the seats are read before the runs are, so the card comes off on the next pass
            self.assertEqual(tick(logs)["word"], "working")
            self.assertIsNone(notify.last("atoll"))

            self.log_out()                                         # ... and out again
            tick(logs)
            # the pass that finds it out takes the mark off, so the run's own row is right
            # at once; the seats were read before the runs were, so the word and the card
            # follow on the next pass -- the three minutes everything here moves in
            self.assertNotIn("login_back_at", run.read_state(directory))
            self.assertEqual(run.waiting_word(run.read_state(directory)),
                             "waiting for claude login")
            out = tick(logs)
        self.assertEqual(out["word"], "needs you")
        self.assertIn("claude login expired", out["reason"])
        self.assertEqual(card.call_count, 2)                       # a new episode, a new card
        self.assertTrue(any("went out again" in line for line in logs), logs)

    def test_a_login_back_inside_the_retry_window_is_never_reported_as_expired(self):
        # The launch failed, so the next one is paced.  The login then goes out and comes
        # back inside that window: the pacing is the launch's business and nobody else's,
        # and the run must not spend it telling the owner to log in to what he has.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        seat = {"name": "atoll", "exited": False, "legacy": False}
        self.log_out(False)
        logs = []
        with patch.object(run, "spawn_bg", side_effect=config.Error("cannot fork")):
            watch.resume_waiting_login(log=logs.append)
        paced = run.read_state(directory)["login_resume_at"]
        self.assertTrue(paced)
        # out again, well inside RESUME_EVERY: the episode is over, and everything it left
        # behind goes with it -- the mark that said `back`, and the stamp that paced a launch
        # timed against it
        self.log_out()
        watch.resume_waiting_login(log=logs.append)
        after = run.read_state(directory)
        self.assertNotIn("login_back_at", after)
        self.assertNotIn("login_resume_at", after)
        self.assertEqual(run.waiting_word(after), "waiting for claude login")
        # ... and back again, still inside the old window: it resumes at once, because that
        # window was timed against a launch this outage already ended
        self.log_out(False)
        launched = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, argv, expected=None:
                          launched.append(d.name) or 0):
            watch.resume_waiting_login(log=logs.append)
        self.assertEqual(launched, [directory.name])

    def test_a_paced_relaunch_never_makes_the_run_look_logged_out(self):
        # The same window, but the login stays back through it: the pass that is throttled
        # still says so, so the run reads `waiting to resume` and its seat reads `working`
        # for the whole ten minutes rather than `login expired` for any of them.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        seat = {"name": "atoll", "exited": False, "legacy": False}
        self.log_out(False)
        logs = []
        with patch.object(run, "spawn_bg", side_effect=config.Error("cannot fork")):
            watch.resume_waiting_login(log=logs.append)
        # strip only the mark, the way an outage between the two passes would
        held = run.read_state(directory)
        held.pop("login_back_at")
        run.save_state(directory, held)
        # this pass is inside the window and starts nothing -- and still records the truth
        with patch.object(run, "spawn_bg", side_effect=AssertionError("relaunched")):
            watch.resume_waiting_login(log=logs.append)
        throttled = run.read_state(directory)
        self.assertEqual(throttled["state"], "waiting_login")
        self.assertTrue(throttled["login_back_at"])
        self.assertEqual(run.waiting_word(throttled), "waiting to resume")
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")):
            found = watch.session_state("atoll", session=seat, cfg=self.cfg)
        self.assertEqual(found["word"], "working")
        self.assertNotIn("login expired", found["reason"])

    def test_a_latch_an_older_watch_json_wrote_is_answered_and_cleared(self):
        # Upgrading a host that was already blocked: `watch.json` carries a login latch the
        # pane raised, back when the pane decided these, so there is no answer on record for
        # it.  The seat carrying one is itself a reason to ask -- otherwise the verb is never
        # asked, the latch never clears, the old card stands, and that seat is out of every
        # recovery path below it for ever.
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.root)})
        seat = {"name": "atoll", "exited": False, "legacy": False}
        notify.record("atoll", "needs", "atoll (Claude Code) needs login: ... and run /login.")
        data = watch.load_state()
        data["stalls"]["atoll"] = {           # no `evidence`, no `auth_out`: an older record
            "kind": "auth", "harness": "claude", "since": time.time() - 9000,
            "told": time.time() - 9000, "notice": notify.last("atoll")["text"]}
        watch.save_state(data)
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="all quiet at the prompt\n"), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True):
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
        self.assertNotIn("atoll", watch.load_state()["stalls"])
        self.assertIsNone(notify.last("atoll"))
        self.assertIs(watch.load_state()["auth_out"]["claude"]["ok"], True)
        # ... and one whose login really is out keeps its latch, answered this time
        self.log_out()
        data = watch.load_state()
        data["stalls"]["atoll"] = {"kind": "auth", "harness": "claude",
                                   "since": time.time() - 9000, "told": time.time() - 9000}
        watch.save_state(data)
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="all quiet at the prompt\n"), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True):
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
        self.assertIn("atoll", watch.load_state()["stalls"])
        self.assertIs(watch.load_state()["auth_out"]["claude"]["ok"], False)

    def test_a_login_already_back_stops_being_told_as_a_login_to_fix(self):
        # The tick found the login back but the launch did not get away.  The run is still
        # parked and still resumes itself -- but nothing may go on telling the owner to log
        # in to something he already has.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        seat = {"name": "atoll", "exited": False, "legacy": False}
        self.assertEqual(run.waiting_word(run.read_state(directory)),
                         "waiting for claude login")
        self.log_out(False)
        logs = []
        with patch.object(run, "spawn_bg", side_effect=config.Error("cannot fork")):
            watch.resume_waiting_login(log=logs.append)
        after = run.read_state(directory)
        self.assertEqual(after["state"], "waiting_login")        # still parked, still retried
        self.assertTrue(after["login_back_at"])
        self.assertEqual(run.waiting_word(after), "waiting to resume")
        self.assertEqual(menu.run_state_word(after), "waiting to resume")
        self.assertTrue(any("could not resume" in line for line in logs), logs)
        # the seat reads the run as working, never as a login of his to go and fix
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")):
            found = watch.session_state("atoll", session=seat, cfg=self.cfg)
        self.assertEqual(found["word"], "working")
        self.assertNotIn("login expired", found["reason"])

    # --- 4: the seat says it once, and stops saying it when the login is back ---

    def test_the_session_reads_the_login_reason_and_returns_to_working(self):
        self.log_out()
        _, directory, state = self.launch()
        seat = {"name": "atoll", "exited": False, "legacy": False}
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="$ "), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "shaped", wraps=notify.shaped) as card:
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
            # one reason, one episode, one card
            found = watch.session_state("atoll", session=seat, cfg=self.cfg)
            self.assertEqual(found["word"], "needs you")
            self.assertEqual(found["reason"], "claude login expired: open it and run /login")
            self.assertEqual(card.call_count, 1)
            # whatever the pane shows in between -- a queued input redrawing the screen is
            # not a login coming back, and the reason does not flap
            for pane in ("Reading the next file", "● Working on it", "$ "):
                with patch.object(watch, "pane_text", return_value=pane):
                    data = watch.load_state()
                    watch.health(self.cfg, data, False, lambda _: None)
                    watch.save_state(data)
                self.assertEqual(watch.session_state("atoll", session=seat,
                                                     cfg=self.cfg)["reason"],
                                 "claude login expired: open it and run /login")
            self.assertEqual(card.call_count, 1)
            # The login comes back.  Both halves of the tick run: the pass that records the
            # answer, and the pass that unparks the run on it -- which is what the seat goes
            # back to working on, because until the run moves the work is still stopped.
            self.log_out(False)
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
            with patch.object(run, "spawn_bg", side_effect=self.adopted):
                watch.resume_waiting_login(log=lambda _: None)
            back = watch.session_state("atoll", session=seat, cfg=self.cfg)
            # ... and the card the outage raised comes off with it
            after = watch.load_state()
            watch.health(self.cfg, after, False, lambda _: None)
            watch.save_state(after)
        self.assertEqual(back["word"], "working")
        self.assertIn("1 running", back["reason"])
        self.assertNotIn("atoll", watch.load_state()["stalls"])
        self.assertIsNone(notify.last("atoll"))

    def test_the_card_names_the_login_a_run_of_this_seats_parked_on(self):
        # The seat runs one harness and its run parked on another: the word and the card come
        # off the same ladder, so they can never name different logins -- and a seat told
        # `claude` while the wall is Muse's has been told nothing useful.
        self.log_out()
        _, directory, state = self.launch()
        state = {**state, "launched_session": "atoll", "waiting_for": "muse"}
        run.save_state(directory, state)
        seat = {"name": "atoll", "exited": False, "legacy": False}
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="$ "), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "shaped", wraps=notify.shaped) as card:
            # claude answers, muse does not: only the harness the run is parked on is out
            def one_out(harness, seat=False):
                return (harness != "muse"), f"{harness}: stub"

            with patch.object(worker, "auth_ok", side_effect=one_out):
                data = watch.load_state()
                watch.health(self.cfg, data, False, lambda _: None)
                watch.save_state(data)
                found = watch.session_state("atoll", session=seat, cfg=self.cfg)
        self.assertEqual(found["word"], "needs you")
        self.assertTrue(found["reason"].startswith("muse login expired"))
        card.assert_called_once()
        said = card.call_args.args[1]
        self.assertIn("Muse", said)             # its own title and its own remedy
        self.assertIn("muse login", said)
        self.assertNotIn("/login", said)
        self.assertEqual(data["stalls"]["atoll"]["harness"], "muse")

    # --- 3: a worker never depends on the seat's OAuth pair ------------------

    def test_the_claude_adapter_exports_the_token_when_the_file_exists(self):
        shipped = REPO / "adapters" / "claude.sh"
        home = self.root / "token-home"
        (home / ".agentkit" / "secrets").mkdir(parents=True)
        out, workspace = self.root / "token-out", self.root / "token-ws"
        workspace.mkdir()
        prompt = self.root / "token-prompt.md"
        prompt.write_text("say nothing\n")
        # a `claude` that answers with the one thing under test: what it was given
        fakebin = self.root / "token-bin"
        fakebin.mkdir()
        (fakebin / "claude").write_text(
            '#!/usr/bin/env bash\nprintf \'{"token":"%s"}\\n\' "${CLAUDE_CODE_OAUTH_TOKEN-unset}"\n')
        (fakebin / "claude").chmod(0o755)

        def turn():
            import subprocess
            env = {**os.environ, **self.sealed(), "HOME": str(home)}
            env["PATH"] = f"{fakebin}:{env['PATH']}"
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            subprocess.run(["bash", str(shipped), "run", "m", "e", str(workspace),
                            str(prompt), str(out)], env=env, capture_output=True, check=False)
            return (out / "events.jsonl").read_text()

        self.assertIn('"token":"unset"', turn())       # no file: today's behaviour, unchanged
        token = home / ".agentkit" / "secrets" / "claude_oauth_token"
        token.write_text("sk-ant-oat01-fixture\n")
        token.chmod(0o600)
        self.assertIn('"token":"sk-ant-oat01-fixture"', turn())

    def test_the_claude_adapter_auth_verb_reads_the_token_then_the_expiry(self):
        shipped = REPO / "adapters" / "claude.sh"
        home = self.root / "auth-home"
        (home / ".agentkit" / "secrets").mkdir(parents=True)
        (home / ".claude").mkdir(parents=True)
        creds = home / ".claude" / ".credentials.json"

        def ask(*argv):
            import subprocess
            env = {**os.environ, **self.sealed(), "HOME": str(home),
                   "CLAUDE_CODE_OAUTH_TOKEN": ""}
            done = subprocess.run(["bash", str(shipped), "auth", *argv], env=env,
                                  capture_output=True, encoding="utf-8", check=False)
            return done.returncode, (done.stdout + done.stderr).strip()

        code, said = ask()
        self.assertEqual(code, 1)                      # nothing to authenticate with
        self.assertIn("/login", said)
        # present is not enough: these are a pair the seat refreshes, and a file that records
        # no usable expiry says nothing about whether this one is still good
        for blob in ({"claudeAiOauth": {"accessToken": "x"}},
                     {"claudeAiOauth": {"accessToken": "x", "expiresAt": "soon"}}):
            with self.subTest(blob=blob):
                creds.write_text(json.dumps(blob))
                code, said = ask()
                self.assertEqual((code, len(said.splitlines())), (1, 1), said)
                self.assertIn("no usable expiry", said)
        creds.write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "x", "expiresAt": 1_000_000_000_000}}))
        code, said = ask()
        self.assertEqual((code, "expired" in said), (1, True))
        self.assertEqual(len(said.splitlines()), 1)    # a `no` is one line, never a page
        creds.write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "x", "expiresAt": 9_000_000_000_000}}))
        self.assertEqual(ask()[0], 0)
        # ... and the worker token outranks the pair the seat refreshes, expired or not
        creds.write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "x", "expiresAt": 1_000_000_000_000}}))
        token = home / ".agentkit" / "secrets" / "claude_oauth_token"
        token.write_text("sk-ant-oat01-x\n")
        self.assertEqual(ask()[0], 0)
        # ... but never for the seat, whose own login it is not: a box whose workers are fine
        # can still have a seat showing `Please run /login`, and that is the whole finding
        code, said = ask("seat")
        self.assertEqual((code, "expired" in said), (1, True))
        self.assertEqual(len(said.splitlines()), 1)
        creds.write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "x", "expiresAt": 9_000_000_000_000}}))
        self.assertEqual((ask()[0], ask("seat")[0]), (0, 0))   # both good, both say so
        # A credential that is only there is not one: a token file holding a newline, an
        # access token spelled with nothing behind it, a blob that is not JSON at all.
        token.write_text("\n")
        creds.write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "x", "expiresAt": 1_000_000_000_000}}))
        self.assertEqual(ask()[0], 1)                          # falls through to the pair
        token.write_text("sk-ant-oat01-x\n")
        for blob in ('{"claudeAiOauth": {"accessToken": "", "expiresAt": 9000000000000}}',
                     '{"claudeAiOauth": {"accessToken": null, "expiresAt": 9000000000000}}',
                     'not json at all {{{'):
            with self.subTest(blob=blob):
                creds.write_text(blob)
                code, said = ask("seat")
                self.assertEqual((code, len(said.splitlines())), (1, 1), said)

    def test_a_worker_token_never_answers_for_the_seat_the_tick_is_watching(self):
        # The tick asks `auth seat`, so a long-lived worker token cannot hide a seat that is
        # showing `Please run /login` -- the two logins expire apart, and the one the owner
        # has to fix is the seat's.
        asked = []

        def verb(harness, seat=False):
            asked.append((harness, seat))
            return (False, f"{harness}: the seat login expired") if seat else (True, "worker")

        seat = {"name": "atoll", "exited": False, "legacy": False}
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.root)})
        with patch.object(worker, "auth_ok", side_effect=verb), \
                patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text",
                             return_value=watch.auth_expiry("claude")[2][0]), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "shaped", wraps=notify.shaped) as card:
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
            found = watch.session_state("atoll", session=seat, cfg=self.cfg)
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "claude login expired: open it and run /login")
        card.assert_called_once()
        self.assertEqual(asked, [("claude", True)])   # the seat's login, and only that

    def test_every_shipped_adapter_answers_the_auth_verb_in_one_line(self):
        import subprocess
        home = self.root / "verb-home"
        home.mkdir()
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                done = subprocess.run(["bash", str(REPO / "adapters" / f"{harness}.sh"), "auth"],
                                      env={**os.environ, **self.sealed(), "HOME": str(home),
                                           "CLAUDE_CODE_OAUTH_TOKEN": "", "META_API_KEY": ""},
                                      capture_output=True, encoding="utf-8", check=False)
                self.assertIn(done.returncode, (0, 1))
                said = [line for line in (done.stdout + done.stderr).splitlines()
                        if line.strip()]
                self.assertEqual(len(said), 1, said)
        # One line on both codes, or it did not answer.  None, never True and never False:
        # a turn is launched on a non-answer, and nothing an answer earned is undone by one.
        for script, why in (
                ('set -u\necho nope >&2\nexit 2\n', "nope"),        # no such verb
                ('echo a >&2; echo b >&2\nexit 1\n', "b"),          # a page, not a reason
                ('exit 0\n', ""),                                    # a yes nobody said
                ('echo one; echo two\nexit 0\n', "two"),            # nor this one
                ('echo "  "\nexit 0\n', "")):                       # nor this one
            with self.subTest(script=script):
                self.adapter("claude", "#!/usr/bin/env bash\n" + script)
                self.assertEqual(worker.auth_ok("claude"), (None, why))
        (self.adapters / "claude.sh").chmod(0o644)                     # nor one nobody can run
        self.assertEqual(worker.auth_ok("claude"), (None, ""))
        # ... and a turn goes ahead on one, exactly as it did before the verb existed
        self.adapter("claude", ADAPTER.replace("__STATE__", str(self.fixture))
                     .replace("__H__", "claude").replace("auth)", "auth) exit 2 ;;\nnever)"))
        code, _, _, _ = worker.call(self.cfg, "opus", "do it", self.root, self.root / "unsure")
        self.assertEqual(code, 0)

    def test_an_adapter_that_cannot_answer_never_lifts_a_login_already_found(self):
        # A `no` is a fact; a verb that fell over next pass is not a `yes`.  The card stays
        # up, the run stays parked, and the tick does not restart work nothing authenticated.
        # The seat's own screen is showing its harness's logout words, which is what makes
        # the tick ask about the seat's login in the first place.
        self.log_out()
        _, directory, state = self.launch()
        run.save_state(directory, {**state, "launched_session": "atoll"})
        config.save_session(self.cfg, "atoll", "opus", ["astra"], {"cwd": str(self.work)})
        seat = {"name": "atoll", "exited": False, "legacy": False}
        pane = watch.auth_expiry("claude")[2][0]
        with patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value=pane), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "shaped", wraps=notify.shaped) as card:
            data = watch.load_state()
            watch.health(self.cfg, data, False, lambda _: None)
            watch.save_state(data)
            self.assertIs(watch.load_state()["auth_out"]["claude"]["ok"], False)
            since = watch.load_state()["auth_out"]["claude"]["at"]
            # the adapter falls over, then exits 0 saying nothing at all -- a yes nobody
            # said.  Neither moves anything, and nobody is told twice.
            for script in ('#!/usr/bin/env bash\necho boom >&2\nexit 2\n',
                           '#!/usr/bin/env bash\nexit 0\n',
                           '#!/usr/bin/env bash\necho one; echo two\nexit 0\n'):
                for harness in self.harnesses:
                    self.adapter(harness, script)
                data = watch.load_state()
                watch.health(self.cfg, data, False, lambda _: None)
                watch.save_state(data)
            found = watch.session_state("atoll", session=seat, cfg=self.cfg)
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "claude login expired: open it and run /login")
        self.assertEqual(watch.load_state()["auth_out"]["claude"], {
            "ok": False, "why": "claude: the token expired; run /login", "at": since})
        self.assertEqual(card.call_count, 1)
        self.assertIn("atoll", watch.load_state()["stalls"])
        # ... and the run is not resumed on a verb that never said yes
        logs = []
        with patch.object(run, "spawn_bg", side_effect=AssertionError("resumed")):
            watch.resume_waiting_login(log=logs.append)
        self.assertEqual(logs, [])
        self.assertEqual(run.read_state(directory)["state"], "waiting_login")

    # --- 3b: the installer mints the token once ------------------------------

    def test_the_installer_skips_setup_token_when_the_file_exists(self):
        import subprocess
        body = (REPO / "install.sh").read_text()
        start = body.index("claude_worker_token() {")
        function = body[start:body.index("\n}\n", start) + 3]
        home = self.root / "install-home"
        (home / ".agentkit" / "secrets").mkdir(parents=True)
        token = home / ".agentkit" / "secrets" / "claude_oauth_token"
        ran = home / "setup-token-ran"
        fakebin = self.root / "install-bin"
        fakebin.mkdir()
        (fakebin / "claude").write_text(
            f'#!/usr/bin/env bash\necho "$*" >>{ran}\necho sk-ant-oat01-minted\n')
        (fakebin / "claude").chmod(0o755)
        # the installer's own section, on a script of its own, so the answer it reads comes
        # from stdin the way a terminal gives it and not out of the script it is running
        script = self.root / "install-slice.sh"
        script.write_text(f'set -euo pipefail\nAK={home}/.agentkit\nROLE=server SANDBOX=0 TTY=1\n'
                          'have() { command -v "$1" >/dev/null 2>&1; }\n'
                          'note() { echo "note: $*" >&2; }\n' + function + "\nclaude_worker_token\n")
        env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}"}

        def install():
            return subprocess.run(["bash", str(script)], input="sk-ant-oat01-pasted\n",
                                  env=env, capture_output=True, encoding="utf-8", check=False,
                                  cwd=str(home))

        token.write_text("sk-ant-oat01-already-there\n")
        done = install()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(ran.exists())                 # never run again once the file is there
        self.assertEqual(token.read_text(), "sk-ant-oat01-already-there\n")
        self.assertNotIn("setup-token", done.stdout + done.stderr)
        # absent, and there is somebody to ask: minted once, 0600, and named in the output
        token.unlink()
        done = install()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(ran.read_text().split(), ["setup-token"])
        self.assertEqual(token.read_text(), "sk-ant-oat01-pasted\n")
        self.assertEqual(oct(token.stat().st_mode)[-3:], "600")
        self.assertIn("claude_oauth_token written", done.stdout)
        # and the pending list names it while the file is absent
        self.assertIn("claude setup-token", (REPO / "install.sh").read_text())

    def test_no_exit_from_a_parked_login_leaves_a_stamp_behind(self):
        # `login_back_at` and `login_resume_at` are one episode's two stamps: wherever one
        # comes off, the other comes with it, or a later recovery sits out a window timed
        # against a launch that is already over.  A failed launch leaves both behind...
        self.log_out()
        _, directory, _ = self.launch()
        self.log_out(False)
        with patch.object(run, "spawn_bg", side_effect=config.Error("cannot fork")):
            watch.resume_waiting_login(log=lambda _: None)
        state = run.read_state(directory)
        self.assertTrue(state["login_back_at"])
        self.assertTrue(state["login_resume_at"])
        # ... and being marked anything but parked takes both off with the harness
        run.mark_state(directory, "exhausted", "out of window")
        after = run.read_state(directory)
        self.assertNotIn("waiting_for", after)
        self.assertNotIn("login_back_at", after)
        self.assertNotIn("login_resume_at", after)
        # ... and so does the worktree going missing while the login is back
        run.mark_state(directory, "waiting_login", "claude login expired")
        state = run.read_state(directory)
        state.update(waiting_for="claude", login_back_at=time.time(),
                     login_resume_at=time.time() - watch.RESUME_EVERY - 1,
                     worktree=str(self.root / "nowhere"))
        run.save_state(directory, state)
        watch.resume_waiting_login(log=lambda _: None)
        after = run.read_state(directory)
        self.assertEqual(after["state"], "interrupted")
        self.assertNotIn("waiting_for", after)
        self.assertNotIn("login_back_at", after)
        self.assertNotIn("login_resume_at", after)


if __name__ == "__main__":
    unittest.main(verbosity=2)

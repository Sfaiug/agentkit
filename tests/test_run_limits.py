"""v5f: nothing in a run waits forever, and a run that stops says so.  Entirely offline.

Real processes throughout -- fake adapters that sleep, done-when commands that spawn children,
a real git repo with a bare origin whose hook rejects a push -- because the thing under test is
a kill, and a mocked kill proves nothing.  The limits are made small by patching the loop constants; old task keys are ignored.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run, usage, watch, worker

URL = "https://github.com/fixture/repo/pull/7"
SLEEP = time.sleep                  # the real one, kept for the waits the fixture itself needs

# a git that stops on whatever `slow-git` names, and is the real git for everything else
GIT_SHIM = '''import os, pathlib, sys, time
marker = pathlib.Path(os.environ["LIMITS_FIXTURE"]) / "slow-git"
want = marker.read_text().split() if marker.exists() else []
args = sys.argv[1:]
if want and any(args[i:i + len(want)] == want for i in range(len(args) - len(want) + 1)):
    time.sleep(60)
os.execv(REAL_GIT, ["git"] + sys.argv[1:])
'''

ADAPTER = '''import json, os, pathlib, subprocess, sys, time
root = pathlib.Path(os.environ["LIMITS_FIXTURE"])
workspace, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
plan = json.loads((root / "plan.json").read_text())
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
events = root / "calls.jsonl"
before = [json.loads(l) for l in events.read_text().splitlines()] if events.exists() else []
call = sum(1 for e in before if e["role"] == role) + 1
with events.open("a") as fh:
    fh.write(json.dumps({"role": role, "call": call, "argv": sys.argv[1:],
                         "session": sys.argv[7] if len(sys.argv) > 7 else None,
                         "prompt": prompt}) + "\\n")
sid = "sid-%s-%s" % (role, call)
# the harness streams its own events; the adapter writes session_id only once the model has
# exited, exactly as claude.sh/codex.sh/muse.sh do -- so a killed turn leaves the id only here
(out / "events.jsonl").write_text(json.dumps({"type": "thread.started", "thread_id": sid}) + "\\n")
(out / "stderr.log").write_text("offline fixture\\n")
if call <= plan.get("hang_" + role, 0):
    time.sleep(600)                       # the limit is what ends this turn, nothing else
(out / "session_id").write_text(sid + "\\n")
if role == "reviewer" and plan.get("move_origin") == call:
    work = root / "repo"                  # origin moves under the run, so it must integrate
    (work / "moved.txt").write_text("origin moved\\n")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "origin moved"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)
if role == "reviewer" and plan.get("arm_git_on_review") == call:
    (root / "slow-git").write_text(plan["arm_git"])   # the next such git never answers
if role == "reviewer":
    (out / "final.md").write_text("VERDICT: PASS\\n\\n## Findings\\n- none\\n")
    sys.exit(0)
(workspace / "work.txt").write_text("executor call %s\\n" % call)
subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "work %s" % call], check=True)
(out / "final.md").write_text("## Summary\\nwrote work.txt on call %s\\n" % call)
'''

GH = '''import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["LIMITS_FIXTURE"])
url = "https://github.com/fixture/repo/pull/7"
args = sys.argv[1:]
with (root / "gh.jsonl").open("a") as fh:
    fh.write(json.dumps(args) + "\\n")
slow = (root / "slow-gh").read_text().split() if (root / "slow-gh").exists() else []
if slow and args[:len(slow)] == slow:
    time.sleep(60)                        # this verb is the one that never answers
refuse = (root / "prompt-gh").read_text().split() if (root / "prompt-gh").exists() else []
if refuse and args[:len(refuse)] == refuse:
    sys.stderr.write("gh: prompts are disabled; run `gh auth login` to authenticate\\n")
    sys.exit(4)
if args[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "fixture/repo", "viewerPermission": "WRITE"}))
elif args[:2] == ["pr", "create"]:
    print(url)
elif args[:2] == ["pr", "merge"]:
    (root / "merged").write_text(" ".join(args))
elif args[:2] == ["pr", "view"]:
    print(json.dumps({"headRefOid": (root / "delivery").read_text().strip(),
                      "baseRefName": "main", "state": "OPEN", "url": url}))
elif args[:2] == ["api", "graphql"]:
    print(json.dumps({"data": {"repository": {"ref": {"branchProtectionRule": None}}}}))
elif args[:2] == ["api", "--paginate"]:
    print("[]")
else:
    sys.stderr.write("unexpected gh %s\\n" % args)
    sys.exit(2)
'''


class Limits(unittest.TestCase):
    """One git repository, fake adapters, a fake gh, and no network anywhere."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5f-", dir=REPO)
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
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "LIMITS_FIXTURE": str(self.root)}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        # nothing here should reach tmux at all; if anything does, it is this suite's own server
        self.script(self.bin / "tmux",
                    'import sys\nassert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv\n'
                    'sys.exit(1)\n')
        self.script(self.bin / "gh", GH)
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.stack.enter_context(patch.object(notify, "shaped",
                                              side_effect=AssertionError("notification")))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(usage, "pick_order", return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(run, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "schedule_gc"))
        # the retry backoff is minutes long and has nothing to do with what is under test here
        self.sleep = self.stack.enter_context(patch.object(run.time, "sleep"))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.plan({})

    # --- the fixture ---------------------------------------------------------

    def script(self, path, text):
        path.write_text(f"#!{sys.executable}\n{text}")
        path.chmod(0o755)

    def plan(self, plan):
        (self.root / "plan.json").write_text(json.dumps(plan))

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        return [r for r in rows if role is None or r["role"] == role]

    def repo(self):
        """A worktree-able checkout on `main`, with a bare origin whose hook can say no."""
        remote, work = self.root / "origin.git", self.root / "repo"
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(remote))
        run.git(self.root, "clone", str(remote), str(work))
        run.git(work, "config", "user.name", "fixture")
        run.git(work, "config", "user.email", "fixture@localhost")
        (work / "README.md").write_text("fixture\n")
        run.git(work, "add", ".")
        run.git(work, "commit", "-m", "base")
        run.git(work, "push", "origin", "main")
        run.git(work, "remote", "set-head", "origin", "main")
        hook = remote / "hooks" / "pre-receive"
        hook.write_text('#!/bin/sh\n[ -e "$LIMITS_FIXTURE/reject-push" ] || exit 0\n'
                        'echo "remote: this push is rejected" >&2\nexit 1\n')
        hook.chmod(0o755)
        self.remote, self.work = remote, work
        return work

    def git_shim(self):
        """Put a `git` on PATH that stops on whatever `slow-git` names, git otherwise."""
        shim = self.root / "shim"
        shim.mkdir(exist_ok=True)
        self.script(shim / "git", GIT_SHIM.replace("REAL_GIT", repr(shutil.which("git"))))
        return patch.dict(os.environ, {"PATH": f"{shim}:{os.environ['PATH']}"})

    def stopped_run(self, name, **extra):
        """A receipt for a run that stopped, with just enough state to report on."""
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(self.task(["true"]).read_text())
        state = {"run_id": name, "title": "A run that stopped", "state": "error",
                 "verdict": None, "error": "`git fetch origin` was killed after 1s: "
                 "nothing here can answer a credential prompt", "executor": "opus",
                 "reviewer": "astra", "rounds": 1, "round_summaries": [], "findings": "",
                 "repo": str(self.work), "worktree": str(self.work), "branch": "main",
                 "base": "origin/main", "base_sha": run.git(self.work, "rev-parse", "HEAD"),
                 "merged": False, "reported": False, **extra}
        run.save_state(directory, state)
        return directory, state

    def task(self, commands, front="", rounds=1):
        path = self.root / "task.md"
        path.write_text(f"---\nrepo: {self.work}\nbase: origin/main\nrounds: {rounds}\n{front}---\n"
                        "# Limit fixture\n\n## Goal\nWrite work.txt.\n\n## Done when\n```bash\n"
                        + "\n".join(commands) + "\n```\n")
        return path

    def launch(self, *argv):
        with redirect_stdout(io.StringIO()):
            code = run.main(list(argv))
        directory = max(run.run_dirs(), key=lambda d: d.name)
        return code, directory, run.read_state(directory)

    def gone(self, pid, limit=10.0):
        """Wait briefly for a pid to disappear; True only if nothing answers to it."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            SLEEP(0.05)
        return False

    # --- 1: done-when runs under a limit -------------------------------------

    def test_v5f_done_when_past_its_limit_fails_the_round_and_leaves_no_children(self):
        self.repo()
        child = self.root / "child.pid"
        hang = f"echo begun; sleep 600 & echo $! > {shlex.quote(str(child))}; wait"
        self.stack.enter_context(patch.object(run, "SILENCE_MINUTES", 0.05))
        task = self.task([hang])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                             "--no-merge")

        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual([r["done_when"] for r in state["round_summaries"]], [False])
        # the output names the command and the limit, and keeps what the command printed
        log = (directory / "round-1" / "donewhen.log").read_text()
        self.assertIn("begun", log)
        self.assertIn("[killed at the limit]", log)
        self.assertIn(f"done-when: stopped after 0.05 min of silence: {hang} (last output: begun)", log)
        # and that is exactly what the fixer is handed
        fixer = (directory / "round-1" / "fixer" / "prompt.md").read_text()
        self.assertIn("The done-when commands failed", fixer)
        self.assertIn("stopped after 0.05 min", fixer)
        # nothing the command spawned outlived it
        self.assertTrue(self.gone(int(child.read_text().strip())))
        # a timeout is a failed check, never a PASS, whatever the reviewer said
        self.assertIn("VERDICT: PASS",
                      (directory / "round-1" / "reviewer" / "final.md").read_text())
        self.assertIn("stopped after 0.05 min", self.calls("reviewer")[-1]["prompt"])
        self.assertEqual(state["review"]["done_when"], False)
        self.assertEqual(state["state"], "fail")
        # the run kept its step record on the way through
        self.assertEqual(state["step"], "reviewer")

    # --- 2: a model turn runs under a limit ----------------------------------

    def test_v5f_model_turn_past_its_limit_is_a_dead_attempt_that_keeps_the_session(self):
        self.repo()
        self.plan({"hang_executor": 1})
        self.stack.enter_context(patch.object(run, "SILENCE_MINUTES", 0.06))
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                             "--no-merge")

        self.assertEqual(code, 0)
        self.assertEqual(state["verdict"], "PASS")
        executors = self.calls("executor")
        self.assertEqual(len(executors), 2)                 # the killed turn, then its retry
        self.assertIsNone(executors[0]["session"])
        self.assertEqual(executors[1]["session"], "sid-executor-1")   # the retry resumes it
        # the kill landed before the adapter could write session_id, as it does in production:
        # the id the retry carried came back out of the stream the harness itself wrote
        killed_turn = directory / "round-1" / "executor"
        self.assertFalse((killed_turn / "session_id").exists())
        self.assertIn("sid-executor-1", (killed_turn / "events.jsonl").read_text())
        self.assertTrue((directory / "round-1" / "executor-retry1" / "final.md").exists())
        text = (directory / "log.txt").read_text()
        self.assertIn("emitted no event for 3s and was killed", text)
        self.assertIn("session sid-executor-1", text)
        self.assertIn("attempt 1", text)
        self.assertEqual(state["exec_session"], "sid-executor-2")

    def test_v5f_turns_past_the_limit_are_resumed_until_one_answers(self):
        self.repo()
        self.plan({"hang_executor": 3})
        self.stack.enter_context(patch.object(run, "SILENCE_MINUTES", 0.06))
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                             "--no-merge")

        self.assertEqual(code, 0)
        self.assertEqual(state["state"], "pass")
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(self.calls("executor")), 4)
        self.assertTrue(self.calls("reviewer"))
        waits = [call.args[0] for call in self.sleep.call_args_list
                 if call.args and call.args[0] in run.TRANSIENT_BACKOFF]
        self.assertEqual(waits, [60, 300, 900])

    # --- 3: git and gh are capped and never prompt ---------------------------

    def test_v5f_every_git_and_gh_call_is_capped_and_prompt_free(self):
        self.repo()
        seen = []
        real = subprocess.run

        def record(cmd, **kwargs):
            if isinstance(cmd, (list, tuple)) and str(cmd[0]) in ("git", "gh"):
                seen.append((list(cmd), kwargs.get("timeout"), kwargs.get("env") or {}))
            return real(cmd, **kwargs)

        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])
        with patch.object(run.subprocess, "run", side_effect=record):
            code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        self.assertTrue([cmd for cmd, _, _ in seen if cmd[0] == "gh"])
        self.assertTrue([cmd for cmd, _, _ in seen if cmd[0] == "git"])
        for cmd, timeout, env in seen:
            self.assertIsInstance(timeout, (int, float), cmd)
            self.assertTrue(0 < timeout <= run.TOOL_CAP, (cmd, timeout))
            self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0", cmd)
            self.assertEqual(env.get("GH_PROMPT_DISABLED"), "1", cmd)

    def test_v5f_a_tool_that_does_not_answer_is_an_error_with_a_remedy(self):
        self.repo()
        slow = self.root / "slow"
        slow.mkdir()
        for tool in ("git", "gh"):
            self.script(slow / tool, 'import time\ntime.sleep(60)\n')
        with patch.dict(os.environ, {"PATH": f"{slow}:{os.environ['PATH']}"}), \
                patch.object(run, "TOOL_CAP", 1):
            # a stop is never handed back as an exit code: git_out raises Stopped with the remedy
            with self.assertRaises(run.Stopped) as stopped_call:
                run.git_out(self.work, "fetch", "origin")
            self.assertIn("was killed after 1s", str(stopped_call.exception))
            self.assertIn("gh auth status", str(stopped_call.exception))
            with self.assertRaisesRegex(config.Error, "was killed after 1s"):
                run.git(self.work, "fetch", "origin")
            self.assertIsNone(run.gh(self.root, "api", "user")[0])
            self.assertIn("then resume the run", run.gh(self.root, "api", "user")[1])
        # a poll keeps a real round trip's budget to the end: shrinking the last poll
        # below one manufactures a stop out of a healthy gh, and the deadline branch that
        # names the unfinished checks never runs
        self.assertEqual(run.poll_cap(time.monotonic() + run.CHECKS_CAP), run.TOOL_CAP)
        self.assertEqual(run.poll_cap(time.monotonic() + 5), run.TOOL_CAP)

    # --- 4: the watch tick reaps ---------------------------------------------

    def test_v5f_watch_tick_reaps_a_dead_run_and_tells_its_owner_once(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        # one run whose pid is gone, and one whose pid was taken over by another process.
        # The tick resumes both in place and tells nobody; a second tick does not launch again.
        recycled = {"boot": "another-boot", "ticks": 1, "started_at": 1.0}
        dead = {"20260914-0900-dead": {"pid": child.pid, "process_identity": None},
                "20260914-0901-recycled": {"pid": os.getpid(), "process_identity": recycled}}
        for name, owner in dead.items():
            directory = config.RUNS / name
            directory.mkdir(parents=True)
            workspace = config.WORK / name
            workspace.mkdir(parents=True)     # a running run always has one to go back to
            run.save_state(directory, {"run_id": name, "title": f"A run that died ({name})",
                                       "state": "running", "verdict": None,
                                       "launched_session": "seat", "executor": "opus",
                                       "reviewer": "astra", "rounds": 1, "round_summaries": [],
                                       "worktree": str(workspace), "scratch": True,
                                       "started_at": time.time() - 600, "reported": False, **owner})
        sent = []
        resumed = []
        self.stack.enter_context(patch.object(notify, "shaped",
                                              side_effect=lambda *a, **k: sent.append((a, k)) or 0))
        self.stack.enter_context(patch.object(
            watch, "launch_resume",
            side_effect=lambda run_id, log=lambda _: None: resumed.append(run_id) or True))
        for name, where in (("retry_pending", notify), ("resume_after_boot", watch),
                            ("health", watch), ("stamp", orch), ("sweep", orch)):
            self.stack.enter_context(patch.object(where, name))
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=(None, "offline")))
        self.stack.enter_context(patch.object(orch, "find", return_value=None))

        for tick in (1, 2):
            with redirect_stdout(io.StringIO()):
                # the tick skips the offline GitHub and ends there, after the resume
                self.assertEqual(watch.main([]), 0)
            for name in dead:
                state = run.read_state(config.RUNS / name)
                self.assertEqual(state["state"], "running", (name, tick))
                self.assertFalse(state.get("recovery_pending"), (name, tick))
                self.assertNotIn("recovery_notified", state)
                self.assertIn("loop process", state["deaths"][0]["reason"])
            self.assertEqual(sorted(resumed), sorted(dead))
        self.assertEqual(sent, [])

    # --- 5: status shows the step and its age --------------------------------

    def test_v5f_status_shows_the_current_step_and_its_age(self):
        now = 1_000_000.0
        for name, step, age in (("20260914-1000-a", "executor", 41 * 60),
                                ("20260914-1001-b", "done-when", 12 * 60),
                                ("20260914-1002-c", "reviewer", 3 * 60),
                                ("20260914-1003-d", "merge", 60)):
            directory = config.RUNS / name
            directory.mkdir(parents=True)
            run.save_state(directory, {"run_id": name, "title": name, "state": "running",
                                       "verdict": None, "executor": "opus", "reviewer": "astra",
                                       "branch": "ak/limit", "rounds": 1, "round_summaries": [],
                                       "started_at": now - 3600, "step": step,
                                       "step_at": now - age, "reported": False,
                                       **run.process_owner()})
        out = io.StringIO()
        with patch.object(run.time, "time", return_value=now), redirect_stdout(out):
            self.assertEqual(run.cmd_status([]), 0)
        printed = out.getvalue()
        for name in ("20260914-1000-a", "20260914-1001-b", "20260914-1002-c", "20260914-1003-d"):
            self.assertRegex(printed, rf"(?m)^{name} +{name} +.* working +opus/astra  "
                                      rf"round 1/1 +1h$")
        # --plain keeps today's words: each live run names its step and its age
        plain_out = io.StringIO()
        with patch.object(run.time, "time", return_value=now), redirect_stdout(plain_out):
            self.assertEqual(run.cmd_status(["--plain"]), 0)
        plain = plain_out.getvalue()
        for name, step, age in (("20260914-1000-a", "executor", "41m"),
                                ("20260914-1001-b", "done-when", "12m"),
                                ("20260914-1002-c", "reviewer", "3m"),
                                ("20260914-1003-d", "merge", "1m")):
            self.assertRegex(plain, rf"(?m)^{name} +running +None +opus/astra +ak/limit "
                                    rf"+{step} {age}$")
        # a finished run's step is over, and still is: step_word says nothing
        done = config.RUNS / "20260914-1003-d"
        state = run.read_state(done)
        self.assertEqual(run.step_word({**state, "state": "pass", "finished_at": now}), "")

    def test_v5f_the_step_is_recorded_in_run_json_as_it_changes(self):
        self.repo()
        task = self.task(["true"])
        _, body, _ = run.parse_task(task)
        directory = config.RUNS / "20260914-1100-steps"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "state": "running", "round_summaries": [],
                 "rounds": 1, "base": "origin/main", "base_sha": "0" * 40, "executor": "opus",
                 "reviewer": "astra", "worktree": str(self.work)}
        run.save_state(directory, state)
        lp = run.Loop(self.cfg, directory, state, {}, lambda m: None, self.work, body,
                      ["true"], body, [])
        for step in ("executor", "done-when", "reviewer", "merge"):
            before = time.time()
            lp.step(step)
            saved = run.read_state(directory)
            self.assertEqual(saved["step"], step)
            self.assertGreaterEqual(saved["step_at"], before)

    # --- 6: old front matter no longer sets time budgets --------------------

    def test_v5f_front_matter_time_keys_are_ignored(self):
        self.repo()
        limits = []
        real = worker.limited

        def recorded(cmd, limit, **kw):
            limits.append((Path(cmd[0]).name, limit, kw.get("silence")))
            return real(cmd, limit, **kw)

        self.stack.enter_context(patch.object(worker, "limited", side_effect=recorded))
        task = self.task(["true"], front="done_when_minutes: 7\nturn_hours: 0.5\nstall_minutes: 90\n")
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra", "--no-merge")
        self.assertEqual(code, 0)
        self.assertEqual((state["silence_minutes"], state["ceiling_hours"]), (20, 6))
        for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
            self.assertNotIn(key, state)
            self.assertEqual((directory / "log.txt").read_text().count(
                f"ignoring {key}: the loop watches for silence"), 1)
        turns = [(limit, silence) for name, limit, silence in limits if name.endswith(".sh")]
        commands = [(limit, silence) for name, limit, silence in limits if name == "bash"]
        self.assertTrue(turns and commands)
        self.assertEqual(set(turns), {(None, 60 * run.SILENCE_MINUTES)})
        self.assertTrue(all(0 < limit <= 3600 * run.CEILING_HOURS and
                            silence == 60 * run.SILENCE_MINUTES for limit, silence in commands))

    # --- 7: a PASS whose delivery failed is never a dead end -----------------

    def test_v5f_run_merge_retries_a_pass_whose_push_was_rejected(self):
        self.repo()
        (self.root / "reject-push").touch()
        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merge_failed"])
        self.assertIsNone(state["pr"])
        self.assertIn("origin already has", state["merge_note"])
        result = (directory / "result.md").read_text()
        self.assertIn(f"retry delivery: ak run merge {directory.name}", result)
        self.assertFalse((self.root / "merged").exists())

        (self.root / "reject-push").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        state = run.read_state(directory)
        self.assertTrue(state["merged"])
        self.assertEqual(state["pr"], URL)
        self.assertEqual(state["delivery_sha"], state["review"]["head_sha"])
        self.assertEqual(run.git(self.remote, "rev-parse", "refs/heads/" + state["branch"]),
                         state["delivery_sha"])
        merged = (self.root / "merged").read_text()
        self.assertIn(f"--match-head-commit {state['delivery_sha']}", merged)
        result = (directory / "result.md").read_text()
        self.assertIn("# PASS, merged", result)
        self.assertNotIn("retry delivery:", result)

    # --- 8: what the reviewer found: no silent loss, no dead end, no unarmed timer ----

    def test_v5f_a_killed_turn_recovers_its_session_from_the_event_stream(self):
        """Every adapter writes session_id last, so a kill leaves the id only in the stream."""
        out = self.root / "turn"
        out.mkdir()
        for events, want in (
                ('{"type":"system","session_id":"claude-1"}\n{"type":"result","session_id":"claude-1"}\n',
                 "claude-1"),
                ('{"type":"thread.started","thread_id":"codex-1"}\n{"type":"item.done"}\n', "codex-1"),
                ('{"stream":{"kind":"session","id":"muse-1"}}\n{"stream":{"kind":"token"}}\n', "muse-1"),
                ('not json at all\n{"type":"result","session_id":"  claude-2  "}\n', "claude-2"),
                ('{"type":"result"}\n[]\n', None),
                ("", None)):
            (out / "events.jsonl").write_text(events)
            self.assertEqual(worker.recovered_session(out), want, events)
        (out / "events.jsonl").unlink()
        self.assertIsNone(worker.recovered_session(out))
        self.assertIsNone(worker.recovered_session(self.root / "nowhere"))

    def test_v5f_done_when_never_starts_a_command_past_the_deadline(self):
        self.repo()
        commands = [f"echo step {n}; sleep 0.4" for n in range(1, 6)]
        self.stack.enter_context(patch.object(run, "CEILING_HOURS", 0.6 / 3600))
        task = self.task(commands)
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                             "--no-merge")
        self.assertEqual(code, 1)
        self.assertEqual([r["done_when"] for r in state["round_summaries"]], [False])
        log = (directory / "round-1" / "donewhen.log").read_text()
        self.assertIn("h ceiling: ", log)
        # the whole list shares the limit: no command gets a slice of its own after it is spent
        self.assertLess(log.count("[exit 0]"), len(commands))
        self.assertNotIn("step 5", log)
        # and a limit that runs out between two commands never starts the second
        spent = directory / "spent.log"
        real = worker.limited
        clock = [0.0]

        def finish_first(*args, **kwargs):
            result = real(*args, **kwargs)
            clock[0] = 600.0
            return result

        with patch.object(run.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(worker, "limited", side_effect=finish_first):
            ok, text = run.run_done_when(["true", "echo never"], self.work, spent, set(), 60)
        self.assertFalse(ok)
        self.assertEqual(text.count("[exit"), 1)            # only the first command ever ran
        self.assertIn("[not run: the done-when limit was already spent]", text)
        self.assertIn("done-when: stopped after 0.0166667h ceiling: echo never "
                      "(the limit was spent before it could start)", text)

    def test_v5f_an_interrupted_turn_takes_its_process_group_with_it(self):
        child = self.root / "interrupted.pid"
        command = ["bash", "-c", f"sleep 600 & echo $! > {shlex.quote(str(child))}; wait"]
        real, interrupted = subprocess.Popen.communicate, []

        def interrupt(proc, *args, **kwargs):
            if interrupted:
                return real(proc, *args, **kwargs)
            interrupted.append(proc.pid)
            while not child.exists():           # let the command get its own child started
                SLEEP(0.02)
            raise KeyboardInterrupt

        with patch.object(subprocess.Popen, "communicate", interrupt), \
                self.assertRaises(KeyboardInterrupt):
            worker.limited(command, 600, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, encoding="utf-8")
        self.assertTrue(self.gone(int(child.read_text().strip())))   # the spawned child
        self.assertTrue(self.gone(interrupted[0]))                   # and the group leader

    def test_v5f_invalid_retired_limits_are_ignored(self):
        self.repo()
        for key, value in (("turn_hours", "inf"), ("turn_hours", "1e999"), ("turn_hours", "nan"),
                           ("turn_hours", "-0"), ("done_when_minutes", "inf"),
                           ("done_when_minutes", str(worker.LIMIT_MAX)),
                           ("done_when_minutes", "0"), ("done_when_minutes", "never"),
                           ("stall_minutes", "never")):
            with self.subTest(key=key, value=value):
                task = self.task(["true"], front=f"{key}: {value}\n")
                code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                                     "--no-merge")
                self.assertEqual(code, 0)
                self.assertEqual((state["silence_minutes"], state["ceiling_hours"]), (20, 6))
                self.assertIn(f"ignoring {key}: the loop watches for silence",
                              (directory / "log.txt").read_text())

    def test_v5f_a_timed_out_gh_stops_the_delivery_and_keeps_it_retryable(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        (self.root / "slow-gh").write_text("repo view")      # the rights check never answers
        task = self.task(["true"])
        with patch.object(run, "TOOL_CAP", 5):
            code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")
        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertTrue(state["merge_failed"])              # so `ak run merge` will take it
        self.assertFalse(state.get("merged"))
        self.assertIn("was killed after 5s", state["merge_note"])
        result = (directory / "result.md").read_text()
        self.assertIn("gh auth status", result)             # the remedy, in result.md
        self.assertIn(f"retry delivery: ak run merge {directory.name}", result)
        self.assertFalse((self.root / "merged").exists())   # nothing was delivered on a guess

        (self.root / "slow-gh").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        self.assertTrue(run.read_state(directory)["merged"])

    def test_v5f_run_merge_survives_a_stopped_gh_and_stays_retryable(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])

        # the same run, back where a failed delivery leaves it, with gh no longer answering
        (self.root / "delivery").write_text(state["delivery_sha"])   # what the PR reports now
        state.update(merged=False, merge_failed=True, merge_note="pushing failed", reported=False)
        run.save_state(directory, state)
        # the first run merged, so its checkout went with the merge; a genuine failed
        # delivery still has its tree, so the retry gets it back
        run.git(state["repo"], "branch", state["branch"], state["delivery_sha"])
        run.git(state["repo"], "worktree", "add", state["worktree"], state["branch"])
        (self.root / "slow-gh").write_text("pr view")
        with patch.object(run, "TOOL_CAP", 5), redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 1)
        state = run.read_state(directory)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merge_failed"])              # still retryable, not a dead end
        self.assertIn("was killed after 5s", state["merge_note"])
        self.assertIn("gh auth status", (directory / "result.md").read_text())
        (self.root / "slow-gh").unlink()
        with patch.object(run, "TOOL_CAP", 5), redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        self.assertTrue(run.read_state(directory)["merged"])

    def test_v5f_a_refused_credential_prompt_reads_like_a_timeout(self):
        self.repo()
        blocked = self.root / "blocked"
        blocked.mkdir()
        self.script(blocked / "git", 'import sys\n'
                    'sys.stderr.write("fatal: could not read Username for \'https://example\': '
                    'terminal prompts disabled\\n")\nsys.exit(128)\n')
        with patch.dict(os.environ, {"PATH": f"{blocked}:{os.environ['PATH']}"}):
            # refused its prompt: the same stop as a timeout, raised rather than returned
            with self.assertRaises(run.Stopped) as refused:
                run.git_out(self.work, "push", "origin", "main")
            self.assertIn("terminal prompts disabled", str(refused.exception))
            self.assertIn("gh auth status", str(refused.exception))   # the same one-line remedy
            self.assertIn("then resume the run", str(refused.exception))
            with self.assertRaisesRegex(config.Error, "then resume the run"):
                run.git(self.work, "push", "origin", "main")
        # and a git that never answered is never read as an empty result, check or no check
        slow = self.root / "slow"
        slow.mkdir()
        self.script(slow / "git", 'import time\ntime.sleep(60)\n')
        with patch.dict(os.environ, {"PATH": f"{slow}:{os.environ['PATH']}"}), \
                patch.object(run, "TOOL_CAP", 1):
            with self.assertRaisesRegex(config.Error, "was killed after 1s"):
                run.git(self.work, "remote", check=False)

    # --- 9: a stop leaves work somebody can pick up, and always says so ---------------

    def test_v5f_a_stop_after_integration_leaves_the_run_resumable(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        # origin moves under the run, so the merge integrates and the saved review is
        # invalidated; v5ac keeps identical patches without a reviewer turn, so the
        # stop is armed on the first review for a git only the post-rebase
        # verification reaches first (review runs it before the reviewer turn).
        self.plan({"move_origin": 1, "arm_git_on_review": 1, "arm_git": "ls-files --others"})
        task = self.task(["true"], rounds=2)
        with self.git_shim(), patch.object(run, "TOOL_CAP", 5):
            code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 1)
        # the review is pending and the rounds are not spent: this is unfinished work, not a
        # finished FAIL, so the state is one both the menu and `ak run resume` act on
        self.assertEqual(state["state"], "exhausted")
        self.assertTrue(state.get("review_pending"))
        self.assertTrue(run.needs_recovery(state))
        self.assertIn("was killed after 5s", state["error"])
        self.assertTrue(state["round_summaries"])
        self.assertIn("--- merge: rebasing", (directory / "log.txt").read_text())
        result = (directory / "result.md").read_text()
        self.assertIn("## Why this run stopped", result)
        self.assertIn("gh auth status", result)
        self.assertFalse((self.root / "merged").exists())
        # `ak run merge` is not the command for this one, and says so rather than pretending
        with self.assertRaisesRegex(config.Error, "merge requires a finished PASS"):
            run.main(["merge", directory.name])

        (self.root / "slow-git").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["resume", directory.name]), 0)
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertTrue(state["merged"])
        # the checkout is gone with the merge; the delivered history still carries origin/main
        self.assertFalse(Path(state["worktree"]).exists())
        merged_history = run.git_out(state["repo"], "merge-base", "--is-ancestor",
                                     "origin/main", state["delivery_sha"])
        self.assertEqual(merged_history[0], 0)

    def test_v5f_an_interrupted_merge_retry_is_reaped_rather_than_lost(self):
        self.repo()
        (self.root / "reject-push").touch()
        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")
        self.assertEqual((code, state["merge_failed"], state["pr"]), (1, True, None))

        (self.root / "reject-push").unlink()
        seen = {}

        def killed(lp, upstream):
            seen.update(run.read_state(directory))      # the receipt a killed retry leaves
            raise KeyboardInterrupt

        with patch.object(run, "integrate", side_effect=killed), \
                redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            run.main(["merge", directory.name])

        # while it delivers, the run owns its receipt: running, this process, at the merge step
        self.assertEqual(seen["state"], "running")
        self.assertEqual(seen["pid"], os.getpid())
        self.assertEqual(seen["step"], "merge")
        self.assertTrue(run.step_word(seen).startswith("merge "))
        self.assertIsNone(seen["finished_at"])
        # so once that process is gone, the reaper picks it up instead of ignoring a PASS
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        state = run.read_state(directory)
        state.update(pid=gone.pid, process_identity=None)
        run.save_state(directory, state)
        state = run.reap(directory, run.read_state(directory))
        self.assertEqual(state["state"], "interrupted")
        self.assertTrue(run.needs_recovery(state))
        self.assertTrue(run.actionable(state))

    def test_v5f_a_stop_is_reported_even_when_the_report_cannot_read_git(self):
        self.repo()
        # the report itself runs git; a git that has stopped must not stop the report too
        directory, state = self.stopped_run("20260914-1200-stopped")
        (self.root / "slow-git").write_text("diff --stat")
        with self.git_shim(), patch.object(run, "TOOL_CAP", 1):
            run.record_result(directory, state)
        result = (directory / "result.md").read_text()
        self.assertIn("## Why this run stopped", result)
        self.assertIn("was killed after 1s", result)
        self.assertIn("cannot read the diff", result)

        # and when the full report cannot be written at all, the file still carries the reason
        other, state = self.stopped_run("20260914-1201-stopped")
        (other / "task.md").unlink()
        run.record_result(other, state)
        result = (other / "result.md").read_text()
        self.assertIn("## Why this run stopped", result)
        self.assertIn("was killed after 1s", result)

        # a stopped tool is work waiting, which is what `exhausted` already means: both the
        # menu and `ak run resume` act on it, where an `error` would be a remedy nobody can use
        third, _ = self.stopped_run("20260914-1202-stopped", state="running")

        def stop():
            raise run.Stopped("`git fetch origin` was killed after 1s: check `gh auth status`")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, third, {}, lambda message: None, job=stop), 1)
        state = run.read_state(third)
        self.assertEqual(state["state"], "exhausted")
        self.assertTrue(run.needs_recovery(state))
        self.assertIn("was killed after 1s", run.recovery_reason(state))

    def test_v5f_repository_discovery_never_reads_a_stop_as_no_repository(self):
        self.repo()
        path = self.root / "task.md"
        (self.root / "slow-git").write_text("--show-toplevel")
        with self.git_shim(), patch.object(run, "TOOL_CAP", 1):
            # a task that names its repo never asks git in the first place
            self.assertEqual(run.task_repo({"repo": str(self.work)}, path), self.work)
            self.assertIsNone(run.task_repo({"repo": "none"}, path))
            # and one that does not must not be handed a scratch workspace by a stopped git
            with self.assertRaisesRegex(config.Error, "was killed after 1s"):
                run.task_repo({}, path)
        (self.root / "slow-git").unlink()
        with self.git_shim():                 # the same call, answering again
            self.assertTrue(Path(run.task_repo({}, path)).is_dir())

    def test_v5f_a_refused_gh_prompt_stops_the_delivery_like_a_timeout(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        (self.root / "prompt-gh").write_text("repo view")   # the rights check is refused a login
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertTrue(state["merge_failed"])
        self.assertFalse((self.root / "merged").exists())   # nothing merged on an assumption
        self.assertIn("prompts are disabled", state["merge_note"])
        result = (directory / "result.md").read_text()
        self.assertIn("gh auth status", result)             # the same one-line remedy
        self.assertIn(f"retry delivery: ak run merge {directory.name}", result)

        (self.root / "prompt-gh").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        self.assertTrue(run.read_state(directory)["merged"])

    # --- 10: second pass -- three timeout paths that lost the classification ----

    def test_v5f_a_rebase_that_stops_is_aborted_and_leaves_a_retryable_pass(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        # the rebase -- and only the rebase -- never answers, so the abort still runs real git
        # the rebase names the pinned tip, so arm the hang on that exact command line
        tip = run.git(self.work, "rev-parse", "origin/main^{commit}")
        self.plan({"arm_git_on_review": 1, "arm_git": f"rebase {tip}"})
        task = self.task(["true"])
        with self.git_shim(), patch.object(run, "TOOL_CAP", 2):
            code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 1)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertTrue(state["merge_failed"])              # so `ak run merge` will take it
        self.assertIsNone(state["pr"])
        # the stop never became a conflict: no conflict round was spent on it
        self.assertEqual([entry["verdict"] for entry in state["round_summaries"]], ["PASS"])
        self.assertFalse(list(directory.glob("round-*/rebase-fixer")))
        text = (directory / "log.txt").read_text()
        self.assertNotIn("conflicted", text)
        self.assertIn("was killed after 2s", text)          # the remedy, in log.txt
        self.assertIn("gh auth status", text)
        self.assertIn("aborted the stopped rebase", text)
        # the worktree is back on the branch head: no rebase state, the work intact
        wt = Path(state["worktree"])
        self.assertFalse(run.in_progress(wt, "rebase"))
        self.assertEqual((wt / "work.txt").read_text(), "executor call 1\n")
        result = (directory / "result.md").read_text()
        self.assertIn("was killed after 2s", result)        # and in result.md
        self.assertIn("gh auth status", result)
        self.assertIn(f"retry delivery: ak run merge {directory.name}", result)

        (self.root / "slow-git").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        state = run.read_state(directory)
        self.assertTrue(state["merged"])

        # and the abort is real: on a genuinely conflicted rebase it drops the state and
        # puts the branch back
        conflict = self.root / "conflict"
        run.git(self.root, "init", "--initial-branch=main", str(conflict))
        run.git(conflict, "config", "user.name", "fixture")
        run.git(conflict, "config", "user.email", "fixture@localhost")
        (conflict / "file.txt").write_text("base\n")
        run.git(conflict, "add", ".")
        run.git(conflict, "commit", "-m", "base")
        run.git(conflict, "checkout", "-b", "side")
        (conflict / "file.txt").write_text("side\n")
        run.git(conflict, "commit", "-am", "side")
        run.git(conflict, "checkout", "main")
        (conflict / "file.txt").write_text("main\n")
        run.git(conflict, "commit", "-am", "main")
        run.git(conflict, "checkout", "side")
        tip = run.git(conflict, "rev-parse", "HEAD")
        code, _ = run.git_out(conflict, "rebase", "main")
        self.assertNotEqual(code, 0)                        # genuinely conflicted
        self.assertTrue(run.in_progress(conflict, "rebase"))
        logged = []

        class LP:
            pass
        lp = LP()
        lp.wt, lp.state, lp.log = conflict, {"branch": "side"}, logged.append
        run.abort_stopped_integration(lp, "rebase")
        self.assertFalse(run.in_progress(conflict, "rebase"))
        self.assertEqual(run.git(conflict, "rev-parse", "HEAD"), tip)
        self.assertTrue(any("aborted the stopped rebase" in line for line in logged))

    def test_v5f_a_stopped_fetch_and_a_stopped_push_take_the_same_path(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])

        for verb in ("fetch origin", "push"):
            (self.root / "slow-git").write_text(verb)
            with self.git_shim(), patch.object(run, "TOOL_CAP", 2):
                code, directory, state = self.launch(str(task), "--exec", "opus", "--review",
                                                    "astra")
            self.assertEqual(code, 1, verb)
            self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"), verb)
            self.assertTrue(state["merge_failed"], verb)    # so `ak run merge` will take it
            self.assertIsNone(state["pr"], verb)
            text = (directory / "log.txt").read_text()
            self.assertIn("was killed after 2s", text, verb)
            self.assertIn("gh auth status", text, verb)
            result = (directory / "result.md").read_text()
            self.assertIn("gh auth status", result, verb)
            self.assertIn(f"retry delivery: ak run merge {directory.name}", result, verb)

            (self.root / "slow-git").unlink()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run.main(["merge", directory.name]), 0, verb)
            self.assertTrue(run.read_state(directory)["merged"], verb)

    def test_v5f_a_stop_before_launch_is_reported_with_its_relaunch(self):
        self.repo()
        path = self.root / "task.md"
        path.write_text("---\n# no repo: discovery runs\n---\n# Launch fixture\n\n## Goal\nWrite work.txt.\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        run_dir = config.RUNS / "20260914-1300-prelaunch"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(path.read_text())
        (run_dir / "log.txt").touch()
        (self.root / "slow-git").write_text("--show-toplevel")
        log = run.logger(run_dir, True)
        with self.git_shim(), patch.object(run, "TOOL_CAP", 1), \
                redirect_stdout(io.StringIO()):
            # the re-raise is what the foreground parent prints, so it carries the remedy
            with self.assertRaises(run.Stopped) as prelaunch:
                run.prepare(run_dir, {"--review-pr": None, "--no-worktree": False,
                                      "--no-merge": False}, log)
        self.assertIn("was killed after 1s", str(prelaunch.exception))
        self.assertIn("gh auth status", str(prelaunch.exception))
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "error")
        self.assertIn("was killed after 1s", state["error"])
        text = (run_dir / "log.txt").read_text()
        self.assertTrue(text.strip())                       # never empty
        self.assertIn("gh auth status", text)               # the remedy, in log.txt
        result = (run_dir / "result.md").read_text()
        self.assertIn("VERDICT: none", result)
        self.assertIn("## Why this run stopped", result)
        self.assertIn("gh auth status", result)
        self.assertIn(f"ak run {run_dir / 'task.md'}", result)

    def test_v5f_a_stop_while_reporting_is_recorded_and_keeps_the_delivery(self):
        self.repo()
        review = {"executor": "opus", "executor_provider": config.model(self.cfg, "opus")["provider"],
                  "reviewer": "astra", "reviewer_provider": config.model(self.cfg, "astra")["provider"],
                  "returncode": 0, "verdict": "PASS",
                  "done_when": True, "head_sha": "0" * 40, "tree_sha": "1" * 40}
        directory, state = self.stopped_run("20260914-1400-report", state="pass",
                                            verdict="PASS", merged=True, review=review)
        (self.root / "slow-git").write_text("diff --stat")
        logged = []
        with self.git_shim(), patch.object(run, "TOOL_CAP", 1):
            run.record_result(directory, state, logged.append)
        result = (directory / "result.md").read_text()
        self.assertIn("# PASS, merged", result)             # the delivery stands
        self.assertIn("cannot read the diff", result)       # the stop is named in the report
        self.assertIn("was killed after 1s", result)
        self.assertNotIn("retry delivery:", result)         # merged: nothing to retry
        self.assertTrue(any("was killed after 1s" in line for line in logged))
        self.assertTrue(any("gh auth status" in line for line in logged))
        saved = run.read_state(directory)
        self.assertEqual((saved["state"], saved["verdict"]), ("pass", "PASS"))
        self.assertTrue(saved["merged"])

    def test_v5f_a_stop_in_exclude_junk_ends_the_run_exhausted_and_resumable(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        (self.root / "slow-git").write_text("rev-parse --git-path")
        task = self.task(["true"])
        with self.git_shim(), patch.object(run, "TOOL_CAP", 2):
            code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")

        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")       # never `error`: resume acts on this
        self.assertEqual(state["round_summaries"], [])      # no fixer round was spent on it
        text = (directory / "log.txt").read_text()
        self.assertIn("was killed after 2s", text)
        self.assertIn("gh auth status", text)
        result = (directory / "result.md").read_text()
        self.assertIn("## Why this run stopped", result)
        self.assertIn("gh auth status", result)
        self.assertTrue(run.needs_recovery(state))

        (self.root / "slow-git").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["resume", directory.name]), 0)
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertTrue(state["merged"])

    @unittest.skipUnless(shutil.which("flock"), "needs flock(1)")
    def test_v5f_a_done_when_grandchild_holding_a_lock_is_stopped_with_its_group(self):
        self.repo()
        lock = self.root / "suite.lock"
        lock.touch()
        holder, taken = self.root / "grandchild.pid", self.root / "taken"
        hang = (f"echo ok 8g; (flock -x {shlex.quote(str(lock))} "
                f"bash -c 'echo taken > {shlex.quote(str(taken))}; sleep 600') & "
                f"echo $! > {shlex.quote(str(holder))}; sleep 600")
        self.stack.enter_context(patch.object(run, "SILENCE_MINUTES", 0.05))
        task = self.task([hang])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra",
                                             "--no-merge")

        self.assertEqual(code, 1)
        self.assertEqual([entry["done_when"] for entry in state["round_summaries"]], [False])
        # donewhen.log keeps the output produced before the stop
        dw = (directory / "round-1" / "donewhen.log").read_text()
        self.assertIn("ok 8g", dw)
        self.assertIn("[killed at the limit]", dw)
        self.assertIn(f"done-when: stopped after 0.05 min of silence: {hang} (last output: ok 8g)", dw)
        # log.txt carries the same line with the last output line
        text = (directory / "log.txt").read_text()
        self.assertIn(f"done-when: stopped after 0.05 min of silence: {hang} (last output: ok 8g)", text)
        # and that is what the fixer is handed: the command, the minutes, the last output line
        fixer = (directory / "round-1" / "fixer" / "prompt.md").read_text()
        self.assertIn(hang, fixer)
        self.assertIn("stopped after 0.05 min", fixer)
        self.assertIn("ok 8g", fixer)
        # the grandchild really held the lock, and no survivor of its process group is left
        self.assertEqual(taken.read_text(), "taken\n")
        self.assertTrue(self.gone(int(holder.read_text().strip())))
        self.assertEqual(subprocess.run(["flock", "-n", str(lock), "true"]).returncode, 0)

    # --- 11: reviewer round 2 -- four findings -------------------------------

    def test_v5f_a_failed_abort_is_reported_honestly_and_claims_nothing(self):
        self.repo()
        conflict = self.root / "conflict"
        run.git(self.root, "init", "--initial-branch=main", str(conflict))
        run.git(conflict, "config", "user.name", "fixture")
        run.git(conflict, "config", "user.email", "fixture@localhost")
        (conflict / "file.txt").write_text("base\n")
        run.git(conflict, "add", ".")
        run.git(conflict, "commit", "-m", "base")
        run.git(conflict, "checkout", "-b", "side")
        (conflict / "file.txt").write_text("side\n")
        run.git(conflict, "commit", "-am", "side")
        run.git(conflict, "checkout", "main")
        (conflict / "file.txt").write_text("main\n")
        run.git(conflict, "commit", "-am", "main")
        run.git(conflict, "checkout", "side")
        code, _ = run.git_out(conflict, "rebase", "main")
        self.assertNotEqual(code, 0)                        # genuinely conflicted
        self.assertTrue(run.in_progress(conflict, "rebase"))
        # what SIGKILL leaves when it kills a git mid-index-write: the abort exits non-zero
        (conflict / ".git" / "index.lock").write_text("")

        class LP:
            pass
        lp = LP()
        logged = []
        lp.wt, lp.state, lp.log = conflict, {"branch": "side"}, logged.append
        run.abort_stopped_integration(lp, "rebase")
        # the abort failed: the state survives, and the log says so instead of claiming clean
        self.assertTrue(run.in_progress(conflict, "rebase"))
        self.assertTrue(any("WARN could not abort the stopped rebase" in line for line in logged),
                        logged)
        self.assertFalse(any("back on its head" in line for line in logged), logged)
        # once the lock is gone the same abort really puts the branch back
        (conflict / ".git" / "index.lock").unlink()
        run.abort_stopped_integration(lp, "rebase")
        self.assertFalse(run.in_progress(conflict, "rebase"))
        self.assertTrue(any("back on its head" in line for line in logged), logged)

    def test_v5f_a_merge_confirmed_by_pr_state_after_a_stopped_call(self):
        self.repo()
        (self.root / "delivery").write_text("unset")
        task = self.task(["true"])
        code, directory, state = self.launch(str(task), "--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])

        # back where a failed delivery leaves it; the merge call itself will stop, but the
        # PR already merged server-side
        (self.root / "delivery").write_text(state["delivery_sha"])
        state.update(merged=False, merge_failed=True, merge_note="pushing failed", reported=False)
        run.save_state(directory, state)
        # the first run merged, so its checkout went with the merge; a genuine failed
        # delivery still has its tree, so the retry gets it back
        run.git(state["repo"], "branch", state["branch"], state["delivery_sha"])
        run.git(state["repo"], "worktree", "add", state["worktree"], state["branch"])
        (self.root / "slow-gh").write_text("pr merge")
        real_gh = run.gh

        def confirm_gh(cwd, *args, **kwargs):
            if "--json" in args and args[args.index("--json") + 1] == "state":
                return 0, "MERGED"
            return real_gh(cwd, *args, **kwargs)

        with patch.object(run, "TOOL_CAP", 5), patch.object(run, "gh", side_effect=confirm_gh), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", directory.name]), 0)
        state = run.read_state(directory)
        self.assertTrue(state["merged"])
        self.assertFalse(state["merge_failed"])
        (self.root / "slow-gh").unlink()

    def test_v5f_a_refused_prompt_for_gh_api_user_is_a_stop_not_a_guess(self):
        self.repo()
        directory = config.RUNS / "20260914-1500-fork"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "title": "fork fixture", "state": "running",
                 "verdict": None, "executor": "opus", "reviewer": "astra", "rounds": 1,
                 "round_summaries": [], "base": "origin/main", "base_sha": "0" * 40,
                 "branch": "ak/fork-fixture", "target": "origin/main",
                 "worktree": str(self.work), "pr": None}
        run.save_state(directory, state)
        lp = run.Loop(self.cfg, directory, state, {}, lambda message: None, self.work,
                      "", [], "", [])
        refused = ("gh: prompts are disabled; run `gh auth login` to authenticate\n"
                   "`gh api user` asked for a credential it may not ask for: nothing here can "
                   "answer a credential prompt, so check `gh auth status` and the remote's "
                   "credentials by hand, then resume the run")
        with patch.object(run, "require_review_pass"), \
                patch.object(run, "git", return_value="origin"), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "gh", side_effect=[(0, ""), (4, refused)]):
            with self.assertRaises(run.Stopped) as fork_stop:
                run.fork_and_pr(lp, "main", "fixture/repo", "READ")
        self.assertIn("prompts are disabled", str(fork_stop.exception))

    def test_v5f_kill_group_never_signals_its_own_process_group(self):
        calls = []
        real_killpg = os.killpg

        def spy(group, sig):
            calls.append((group, sig))
            if group == os.getpgid(0):
                raise AssertionError("kill_group signalled its own process group")
            return real_killpg(group, sig)

        class Proc:
            pid = os.getpid()

        with patch.object(os, "killpg", side_effect=spy):
            worker.kill_group(Proc())
        self.assertEqual(calls, [])

    def test_v5f_a_checks_wait_at_its_deadline_names_the_unfinished_checks(self):
        self.repo()
        directory = config.RUNS / "20260914-1600-checks"
        directory.mkdir(parents=True)
        polls = []

        def slow_gh(cwd, *args, **kwargs):
            if "graphql" in args:
                return ({"data": {"repository": {"ref": {"branchProtectionRule": None}}}},
                        "")
            if args and "check-runs" in args[-1]:
                # a healthy gh that needs longer than a shrunk budget: under the old
                # poll_cap the final poll arrived with 1s and this raised Stopped
                polls.append(kwargs.get("timeout"))
                if kwargs.get("timeout") is not None and kwargs.get("timeout") < 2:
                    raise run.Stopped("`gh api` was killed after 1s: nothing here can "
                                      "answer a credential prompt")
                return ([{"check_runs": [{"id": 1, "name": "ci", "status": "in_progress",
                                          "conclusion": None, "app": {"id": 123}}]}], "")
            return ([[{"type": "required_status_checks",
                       "parameters": {"required_status_checks": [{"context": "ci",
                                                                  "integration_id": 123}]}}]],
                    "")

        class LP:
            pass
        lp = LP()
        lp.target, lp.run_dir, lp.log = "origin/main", directory, lambda message: None
        lp.state = {"delivery_sha": "d" * 40}
        with patch.object(run, "gh_json", side_effect=slow_gh), \
                patch.object(run, "CHECKS_CAP", 0):
            self.assertEqual(run.checks(lp, "https://github.com/me/repo/pull/7"),
                             (False, "required checks did not finish: ci"))
        # every poll kept a real round trip's budget: none was shrunk toward the deadline
        self.assertTrue(polls)
        self.assertTrue(all(budget == run.TOOL_CAP for budget in polls), polls)


if __name__ == "__main__":
    unittest.main(verbosity=2)

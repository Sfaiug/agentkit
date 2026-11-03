"""a worker's long command runs in the foreground.  Entirely offline fixture state."""

import io
import json
import os
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import scripted, stateful
from agentkit import config, gate, gitcall, host, notify, run, turns, worker
from agentkit import record

# The words the task pins, quoted here so the tests fail if the loop rewords them.
HEADER = ("Run long commands, tests included, in the foreground and wait for them; "
          "a turn that ends with a command still running in the background is not finished.")
BACKGROUND = "Background tasks still running after 600s; terminating"

PASS = "VERDICT: PASS\n"
FAIL = "VERDICT: FAIL\n"

# One fake harness for every model in the catalogue: it never leaves the fixture directory,
# records each call (prompt, resumed session, worker environment), and plays a script the
# test wrote -- one step per executor call, a queue of answers for the reviewer.
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["V5W_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt, "session": sys.argv[7:],
        "bash_default": os.environ.get("BASH_DEFAULT_TIMEOUT_MS"),
        "bash_max": os.environ.get("BASH_MAX_TIMEOUT_MS"),
        "sentinel": os.environ.get("V5W_SENTINEL")}) + "\\n")
if role == "reviewer":
    plan = json.loads((root / "reviews.json").read_text())
    answer = plan.pop(0)
    (root / "reviews.json").write_text(json.dumps(plan))
    (out / "final.md").write_text(answer)
    (out / "stderr.log").write_text("")
    (out / "events.jsonl").write_text("")
    (out / "session_id").write_text("session-reviewer")
    sys.exit(0)
key = root / "exec_counter"
n = int(key.read_text()) if key.exists() else 0
key.write_text(str(n + 1))
plan = json.loads((root / "exec_plan.json").read_text())
step = plan[min(n, len(plan) - 1)]
# a turn that dies without answering writes no final.md, the way the real adapters leave a
# failed turn's file alone; worker.call then reads whatever is there, which in a directory
# of the turn's own is nothing
if step.get("write_final", True):
    (out / "final.md").write_text(step.get("final", ""))
(out / "stderr.log").write_text(step.get("stderr", ""))
(out / "events.jsonl").write_text("".join(json.dumps(e) + "\\n" for e in step.get("events", [])))
(out / "session_id").write_text(step.get("session", "session-executor"))
if step.get("deliverable"):
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
sys.exit(step.get("exit", 0))
'''


def clean(finished=True):
    """An executor step that did its work in the foreground, as asked."""
    return {"final": "## Summary\\nFixture work.", "stderr": "", "events": [],
            "session": "sess-1", "deliverable": finished}


class LongCommandsRunInTheForeground(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-v5w-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            # a worker running this file carries its own run's marker, and a failed turn
            # below ends every process marked with the run it inherits
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "V5W_FIXTURE": str(self.root)}))
        # The loop itself may run inside a Claude worker shell that exports the Bash timeout
        # variables this change sets.  Keep them out of the fixture, so what the fake harness
        # records is only what worker.call put there for that harness.  AK_MAX_RUNS=0 goes the
        # same way: it opens the slot gate whose one poll these cases count.  So do a caller's
        # AK_MIN_FREE_MB and AK_MAX_LOAD: judged against the fixed readings below, they can
        # keep that gate shut for good.
        self.stack.enter_context(patch.dict(os.environ))
        for var in ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS", "AK_MAX_RUNS",
                    "AK_MIN_FREE_MB", "AK_MAX_LOAD"):
            os.environ.pop(var, None)
        # Nothing outside the fixture is reachable: no tmux server, harness, GitHub or Discord.
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(gitcall, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        # These adapters start no background commands; process discovery is covered by its
        # own fixture, so this prompt regression never reads the host's process table.
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(gate, "SLOT_POLL", .01))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.task = self.root / "task.md"
        self.exec_plan(clean())
        self.reviews(PASS)
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{scripted(body)}")
        path.chmod(0o755)
        stateful(path, self.root)

    def exec_plan(self, *steps):
        (self.root / "exec_plan.json").write_text(json.dumps(list(steps)))
        (self.root / "exec_counter").write_text("0")

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    @contextmanager
    def loop_sleeps(self):
        """time.sleep patched, with the mock hearing only the waits agentkit.run and its turns ask for.

        `run.time` is the time module, so the patch is every caller's -- the stdlib's too:
        `subprocess.run(timeout=...)`, which worker.call's `auth` probe uses, polls its child
        with time.sleep and spins hundreds of times on a mock that returns at once.  Those
        polls are no wait of the loop's, and the waits pinned below are the loop's own.
        """
        sleep = MagicMock()

        def heard(seconds):
            if sys._getframe(1).f_globals.get("__name__") in (run.__name__, turns.__name__, gate.__name__):
                sleep(seconds)

        with patch.object(run.time, "sleep", heard):
            yield sleep

    def launch(self, rounds=1, done_when="test -f deliverable"):
        """One scratch run, so the loop is the only thing under test: no repo, branch or PR."""
        # the sandbox's own name keeps its run ids its own: a run's sweep ends every
        # process on the host carrying its id, another test's or checkout's too
        self.task.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n"
                             f"# Budget fixture {self.root.name}\n\n"
                             f"## Done when\n```bash\n{done_when}\n```\n")
        before = set(record.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer])
        directory = (set(record.run_dirs()) - before).pop()
        return code, directory, record.read_state(directory)

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def log(self, directory):
        return (directory / "log.txt").read_text()

    def numbers(self, prompt):
        return re.findall(r"up to (\d+) minutes", prompt)

    # --- (a) a Claude worker call carries both variables with the cap in milliseconds ---

    def test_v5w_claude_worker_call_carries_both_timeouts_in_ms(self):
        out = self.root / "wout"
        (self.root / "ws").mkdir()
        code, _, _, _ = worker.call(self.cfg, "opus", "do the thing", self.root / "ws", out,
                                    "executor", None, env={"V5W_SENTINEL": "kept"}, limit=120)
        self.assertEqual(code, 0)
        call = self.calls("executor")[-1]
        cap = str(int(record.CEILING_HOURS * 3600 * 1000))
        self.assertEqual(cap, "21600000")
        self.assertEqual(call["bash_default"], cap)
        self.assertEqual(call["bash_max"], cap)
        self.assertEqual(call["sentinel"], "kept")

    def test_v5w_claude_worker_command_keeps_cap_with_inherited_timeouts(self):
        out = self.root / "wout"
        workspace = self.root / "ws"
        workspace.mkdir()
        self.task.write_text("Fixture work.")
        with patch.dict(os.environ, {"BASH_DEFAULT_TIMEOUT_MS": "1000",
                                     "BASH_MAX_TIMEOUT_MS": "2000"}):
            code = worker.main(["opus", str(self.task), "--workspace", str(workspace),
                                "--out", str(out)])
        self.assertEqual(code, 0)
        call = self.calls("executor")[-1]
        cap = str(int(record.CEILING_HOURS * 3600 * 1000))
        self.assertEqual(call["bash_default"], cap)
        self.assertEqual(call["bash_max"], cap)

    # --- (b) a Codex and a Muse call carry their equivalent or nothing new ---

    def test_v5w_codex_and_muse_calls_carry_nothing_new(self):
        # Checked 0.153.4's config keys and Muse 1.3.0's flags, help and wire schema: neither
        # harness exposes a shell-timeout knob, so their calls carry nothing extra.
        (self.root / "ws").mkdir()
        for model in ("astra", "spark"):
            out = self.root / f"wout-{model}"
            code, _, _, _ = worker.call(self.cfg, model, "do the thing", self.root / "ws", out,
                                        "executor", None, env={"V5W_SENTINEL": "kept"}, limit=120)
            self.assertEqual(code, 0)
        calls = self.calls("executor")
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIsNone(call["bash_default"])
            self.assertIsNone(call["bash_max"])
            self.assertEqual(call["sentinel"], "kept")

    # --- (c) the header sentence is in the executor, fixer and reviewer prompts ---

    def test_v5w_header_sentence_in_executor_fixer_and_reviewer_prompts(self):
        self.exec_plan(clean(), clean())
        self.reviews(FAIL, PASS)
        code, _, state = self.launch(rounds=3)
        self.assertEqual(code, 0, state)
        prompts = {"executor": self.calls("executor")[0]["prompt"],
                   "fixer": self.calls("executor")[1]["prompt"],
                   "reviewer": self.calls("reviewer")[0]["prompt"]}
        for name, prompt in prompts.items():
            with self.subTest(prompt=name):
                self.assertIn(HEADER, prompt)
                self.assertEqual(prompt.count(HEADER), 1)
                self.assertEqual(self.numbers(prompt), [])

    def test_v5w_background_signals_do_not_buy_another_turn(self):
        for stderr, events in ((BACKGROUND, []), ("", [
                {"type": "system", "subtype": "background_tasks_changed", "tasks": ["term-1"]}])):
            with self.subTest(stderr=stderr, events=events):
                self.exec_plan({**clean(), "stderr": stderr, "events": events})
                self.reviews(PASS)
                before = len(self.calls("executor"))
                code, directory, state = self.launch(rounds=1)
                self.assertEqual(code, 0, self.log(directory))
                self.assertEqual(len(self.calls("executor")), before + 1)
                self.assertEqual(state["verdict"], "PASS")

    # --- (f) a clean turn gets no extra call ---

    def test_v5w_clean_turn_gets_no_extra_call(self):
        self.exec_plan(clean())
        self.reviews(PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(len(self.calls("executor")), 1)
        self.assertNotIn("in the background", self.log(directory))

    # A background signal cannot hide a provider failure.

    def test_v5w_background_failure_still_retries(self):
        self.exec_plan(
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": BACKGROUND, "events": [],
             "session": "s1"},
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": BACKGROUND, "events": [],
             "session": "s1"},
            clean())
        workspace = self.root / "ws"
        workspace.mkdir()
        out = self.root / "run" / "round-1" / "executor"
        logged = []
        with self.loop_sleeps() as sleep:
            code, _, _, dead = turns.call_retrying(self.cfg, "opus", "task body", workspace, out,
                                                 "executor", None, logged.append, limit=120)
        self.assertFalse(dead)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls("executor")), 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_any_call(turns.TRANSIENT_BACKOFF[0])
        sleep.assert_any_call(turns.TRANSIENT_BACKOFF[1])

    # --- (i) a background task list the turn emptied is finished ---

    def test_v5w_emptied_background_task_list_is_finished(self):
        self.exec_plan(
            {"final": "## Summary\nWaited for the suite, then reported.", "stderr": "",
             "events": [{"type": "system", "subtype": "background_tasks_changed",
                         "tasks": ["term-1"]},
                        {"type": "system", "subtype": "background_tasks_changed",
                         "tasks": []}],
             "session": "s1"})
        workspace = self.root / "ws"
        workspace.mkdir()
        out = self.root / "run" / "round-1" / "executor"
        logged = []
        with self.loop_sleeps() as sleep:
            code, text, _, dead = turns.call_retrying(self.cfg, "opus", "task body", workspace,
                                                    out, "executor", None, logged.append,
                                                    limit=120)
        self.assertFalse(dead)
        self.assertEqual(code, 0)
        self.assertIn("Waited for the suite", text)
        self.assertEqual(len(self.calls("executor")), 1)
        self.assertFalse(sleep.called)
        self.assertFalse(any("in the background" in line for line in logged))

if __name__ == "__main__":
    unittest.main()

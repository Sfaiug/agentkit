"""agentkit v5w: a worker's long command runs in the foreground.  Entirely offline fixture state."""

import io
import json
import os
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, worker

# The words the task pins, quoted here so the tests fail if the loop rewords them.
HEADER = ("Run long commands, the test suite "
          "included, in the foreground and wait for them; a turn that ends with a command "
          "still running in the background is not finished.")
FINISH = ("The command you left in the background was stopped when your turn ended. Run it in "
          "the foreground now, wait for it, and report.")
BACKGROUND = "Background tasks still running after 600s; terminating"
ASKING = "ended its turn with a command still in the background; asking it to finish in the foreground"

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
        tmp = tempfile.TemporaryDirectory(prefix=".v5w-", dir=REPO)
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
            "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "V5W_FIXTURE": str(self.root)}))
        # The loop itself may run inside a Claude worker shell that exports the Bash timeout
        # variables this change sets.  Keep them out of the fixture, so what the fake harness
        # records is only what worker.call put there for that harness.
        self.stack.enter_context(patch.dict(os.environ))
        for var in ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS"):
            os.environ.pop(var, None)
        # Nothing outside the fixture is reachable: no tmux server, harness, GitHub or Discord.
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
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
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def exec_plan(self, *steps):
        (self.root / "exec_plan.json").write_text(json.dumps(list(steps)))
        (self.root / "exec_counter").write_text("0")

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    @contextmanager
    def loop_sleeps(self):
        """time.sleep patched, with the mock hearing only the waits agentkit.run asks for.

        `run.time` is the time module, so the patch is every caller's -- the stdlib's too:
        `subprocess.run(timeout=...)`, which worker.call's `auth` probe uses, polls its child
        with time.sleep and spins hundreds of times on a mock that returns at once.  Those
        polls are no wait of the loop's, and the waits pinned below are the loop's own.
        """
        sleep = MagicMock()

        def heard(seconds):
            if sys._getframe(1).f_globals.get("__name__") == run.__name__:
                sleep(seconds)

        with patch.object(run.time, "sleep", heard):
            yield sleep

    def launch(self, rounds=1, done_when="test -f deliverable"):
        """One scratch run, so the loop is the only thing under test: no repo, branch or PR."""
        self.task.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# Budget fixture\n\n"
                             f"## Done when\n```bash\n{done_when}\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

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
        cap = str(int(run.CEILING_HOURS * 3600 * 1000))
        self.assertEqual(cap, "21600000")
        self.assertEqual(call["bash_default"], cap)
        self.assertEqual(call["bash_max"], cap)
        self.assertEqual(call["sentinel"], "kept")

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

    # --- (d) an unfinished turn gets exactly one foreground finish on the same session ---

    def test_v5w_unfinished_turn_gets_one_foreground_finish_on_the_same_session(self):
        self.exec_plan(
            {"final": "I will report as soon as the gate finishes.", "stderr": BACKGROUND + "\n",
             "events": [], "session": "sess-1"},
            {"final": "## Summary\nRan the suite in the foreground.", "stderr": "",
             "events": [], "session": "sess-1", "deliverable": True})
        self.reviews(PASS)
        with self.loop_sleeps() as sleep:
            code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(sleep.call_args_list, [call(run.SLOT_POLL)])
        calls = self.calls("executor")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["session"], [])
        self.assertEqual(calls[1]["session"], ["sess-1"])
        self.assertIn(FINISH, calls[1]["prompt"])
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertIn(f"executor-scratch {self.executor} {ASKING}", self.log(directory))
        self.assertIn("Ran the suite in the foreground.", state["round_summaries"][0]["summary"])
        # each turn kept artifacts of its own: the first turn's diagnostics survived the
        # second, whose answer lives beside them rather than over them
        first = directory / "round-1" / "executor"
        second = directory / "round-1" / "executor-retry-foreground"
        self.assertIn(BACKGROUND, (first / "stderr.log").read_text())
        self.assertNotIn(FINISH, (first / "prompt.md").read_text())
        self.assertIn(FINISH, (second / "prompt.md").read_text())
        self.assertIn("Ran the suite in the foreground.", (second / "final.md").read_text())

    # --- (e) a second unfinished turn warns once and the loop carries on ---

    def test_v5w_second_unfinished_turn_warns_once_and_carries_on(self):
        self.exec_plan(
            {"final": "I will report as soon as the gate finishes.", "stderr": BACKGROUND + "\n",
             "events": [], "session": "sess-1"},
            {"final": "I will report as soon as the gate finishes.", "stderr": BACKGROUND + "\n",
             "events": [], "session": "sess-1"})
        self.reviews(PASS)
        code, directory, state = self.launch(rounds=1, done_when="true")
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(len(self.calls("executor")), 2)
        warns = [line for line in self.log(directory).splitlines() if "WARN" in line]
        self.assertEqual(len(warns), 1, self.log(directory))
        self.assertIn("still in the background", warns[0])
        self.assertIn("done-when: all passed", self.log(directory))
        self.assertEqual(state["verdict"], "PASS")

    # --- (f) a clean turn gets no extra call ---

    def test_v5w_clean_turn_gets_no_extra_call(self):
        self.exec_plan(clean())
        self.reviews(PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(len(self.calls("executor")), 1)
        self.assertNotIn("in the background", self.log(directory))

    # --- (g) the unfinished turn does not consume a transport attempt ---

    def test_v5w_unfinished_turn_consumes_no_transport_attempt(self):
        self.exec_plan(
            {"final": "placeholder", "stderr": BACKGROUND + "\n", "events": [],
             "session": "s1"},
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": "", "events": [],
             "session": "s1"},
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": "", "events": [],
             "session": "s1"},
            clean())
        workspace = self.root / "ws"
        workspace.mkdir()
        out = self.root / "run" / "round-1" / "executor"
        logged = []
        with self.loop_sleeps() as sleep:
            code, _, _, dead = run.call_retrying(self.cfg, "opus", "task body", workspace, out,
                                                 "executor", None, logged.append, limit=120)
        self.assertFalse(dead)
        self.assertEqual(code, 0)
        # the finish call plus the transient waits ran, with a backoff only between
        # the attempts themselves
        self.assertEqual(len(self.calls("executor")), 4)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_any_call(run.TRANSIENT_BACKOFF[0])
        sleep.assert_any_call(run.TRANSIENT_BACKOFF[1])
        self.assertTrue(any(ASKING in line for line in logged))

    # --- (h) a background_tasks_changed event with tasks is unfinished too ---

    def test_v5w_background_event_with_tasks_gets_a_foreground_finish(self):
        # what installed Claude 2.1.263 streams: the marker is the subtype, not the type
        self.exec_plan(
            {"final": "I will report as soon as the gate finishes.", "stderr": "",
             "events": [{"type": "system", "subtype": "background_tasks_changed",
                         "tasks": ["term-1"]}],
             "session": "sess-1"},
            {"final": "## Summary\nRan the suite in the foreground.", "stderr": "",
             "events": [], "session": "sess-1", "deliverable": True})
        self.reviews(PASS)
        with self.loop_sleeps() as sleep:
            code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(sleep.call_args_list, [call(run.SLOT_POLL)])
        calls = self.calls("executor")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["session"], ["sess-1"])
        self.assertIn(FINISH, calls[1]["prompt"])
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertIn(f"executor-scratch {self.executor} {ASKING}", self.log(directory))

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
            code, text, _, dead = run.call_retrying(self.cfg, "opus", "task body", workspace,
                                                    out, "executor", None, logged.append,
                                                    limit=120)
        self.assertFalse(dead)
        self.assertEqual(code, 0)
        self.assertIn("Waited for the suite", text)
        self.assertEqual(len(self.calls("executor")), 1)
        self.assertFalse(sleep.called)
        self.assertFalse(any("in the background" in line for line in logged))

    # --- (j) a finish turn that leaves no answer retries on empty, not on stale text ---

    def test_v5w_failed_finish_without_an_answer_retries_on_empty(self):
        self.exec_plan(
            {"final": "I will report as soon as the gate finishes.", "stderr": BACKGROUND + "\n",
             "events": [], "session": "s1"},
            {"exit": 1, "write_final": False, "stderr": "boom", "events": [],
             "session": "s1"},
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": "", "events": [],
             "session": "s1"},
            {"final": "HTTP 500 Overloaded", "exit": 1, "stderr": "", "events": [],
             "session": "s1"},
            clean())
        workspace = self.root / "ws"
        workspace.mkdir()
        out = self.root / "run" / "round-1" / "executor"
        logged = []
        with self.loop_sleeps() as sleep:
            code, text, _, dead = run.call_retrying(self.cfg, "opus", "task body", workspace,
                                                    out, "executor", None, logged.append,
                                                    limit=120)
        self.assertFalse(dead)
        self.assertEqual(code, 0)
        # the failed finish wrote no final.md of its own, so it retried on an empty answer --
        # never the first turn's placeholder -- and the answer carries the successful
        # attempt's own work rather than anything stale
        self.assertIn("Fixture work", text)
        self.assertNotIn("report as soon as the gate", text)
        self.assertEqual(len(self.calls("executor")), 5)
        self.assertEqual(sleep.call_count, 3)
        self.assertTrue(any(ASKING in line for line in logged))


if __name__ == "__main__":
    unittest.main()

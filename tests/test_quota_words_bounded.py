"""A worker turn's failure counts only in whole words the harness itself said.

A `429` or `529` inside a longer number -- a request id, a byte count -- is no refusal, and a
quota word in the model's own answer parks nothing and waits for nothing.  The words the loop
used to keep itself now live in each adapter manifest's `[stall]`, and still hand a turn over
or wait it out as before.  Fake adapters answer from a plan file, the manifests are the
repository's own, and HOME is temporary: no model, meter or real process is reached.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage  # noqa: E402

# Every harness's adapter: `auth` answers yes, and `run` plays the next row of plan.json, the
# last row again once it is the only one left.
ADAPTER = '''import json, pathlib, sys
if sys.argv[1] == "auth":
    print("fake login")
    sys.exit(0)
if sys.argv[1] != "run":
    sys.exit(2)
plan = pathlib.Path(__file__).with_name("plan.json")
rows = json.loads(plan.read_text())
row = rows.pop(0) if len(rows) > 1 else rows[0]
plan.write_text(json.dumps(rows))
out = pathlib.Path(sys.argv[6])
for name in ("final.md", "stderr.log", "events.jsonl"):
    (out / name).write_text(row.get(name, ""))
(out / "session_id").write_text("s1")
sys.exit(row.get("code", 0))
'''
DONE = {"code": 0, "final.md": "## Summary\nDone.\n"}


class Clock:
    """`time` as run.py sees it, with only run.py's own sleeps going to `sleep`."""

    def __init__(self, sleep):
        self.sleep = sleep

    def __getattr__(self, name):
        return getattr(time, name)


def stall(harness):
    """The `[stall]` table of that harness's manifest, as the repository ships it."""
    return tomllib.loads((REPO / f"adapters/{harness}.toml").read_text())["stall"]


class QuotaWordsBounded(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-quota-words-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, root / key.lower()))
        self.adapters = root / "adapters"
        self.adapters.mkdir()
        for manifest in (REPO / "adapters").glob("*.toml"):
            script = self.adapters / f"{manifest.stem}.sh"
            script.write_text(f"#!{sys.executable}\n{ADAPTER}")
            script.chmod(0o755)
        env = {k: v for k, v in os.environ.items()
               if k not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR",
                            "AGENTKIT_RUN_DIR", "AGENTKIT_SESSION", "AGENTKIT_ACCOUNT")}
        env.update(HOME=str(root), AGENTKIT_ADAPTER_DIR=str(self.adapters), AK_RUN_DEPTH="0",
                   AK_MAX_RUNS="0", AGENTKIT_DISCORD_WEBHOOK="off", PYTHONDONTWRITEBYTECODE="1")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        self.cfg = config.load()
        self.work = root / "workspace"
        self.work.mkdir()
        # the fake usage layer: which account a turn runs on, and what gets parked or spent
        self.account, self.marked, self.lines = None, [], []
        self.stack.enter_context(patch.object(
            usage, "account",
            side_effect=lambda cfg, provider: (self.account, False) if self.account
            else (None, None)))
        self.stack.enter_context(patch.object(
            usage, "mark_exhausted", side_effect=lambda *a, **k: self.marked.append(a)))
        self.stack.enter_context(patch.object(usage, "replenish", return_value=(False, 0.0)))
        # a wait nobody expects fails at once, rather than replaying the same turn for ever
        self.sleep = MagicMock(side_effect=AssertionError("waited"))
        self.stack.enter_context(patch.object(run, "time", Clock(self.sleep)))

    def turn(self, model, *rows):
        (self.adapters / "plan.json").write_text(json.dumps(list(rows)))
        return run.call_retrying(self.cfg, model, "Do the task.", self.work,
                                 self.root / "run" / "round-1" / "executor", "executor", None,
                                 self.lines.append, limit=120)

    def test_a_429_or_529_inside_a_longer_number_neither_parks_nor_waits(self):
        # Every one of these harnesses lists `429` as a spent window and `529` as a refusal.
        said = "Stopped: request req_84290 wrote 15290 bytes in 1.529s."
        for model, harness in (("opus", "claude"), ("astra", "codex"), ("spark", "muse")):
            with self.subTest(model=model):
                self.assertIn("429", stall(harness)["quotas"])
                self.assertIn("529", stall(harness)["refusals"])
                code, text, session, dead = self.turn(
                    model, {"code": 1, "final.md": said, "stderr.log": "exit after 45290ms\n"})
                self.assertEqual((code, text, session, dead), (1, said, "s1", False))
                self.assertEqual(self.marked, [])
                self.sleep.assert_not_called()

    def test_a_quota_word_in_the_model_s_answer_parks_nothing(self):
        self.account = "second"
        answer = ("## Summary\nTaught the retry to read `usage limit reached` and "
                  "`429 Too Many Requests` as a spent window.\n")
        code, text, _, _ = self.turn("opus", {"code": 1, "final.md": answer})
        self.assertEqual((code, text), (1, answer))
        self.assertEqual(self.marked, [])
        self.assertFalse([line for line in self.lines if "ran dry" in line], self.lines)
        # nor does an outage the answer talks about wait for anything
        answer = ("## Summary\nThe client now retries `API Error: 529 Overloaded` and "
                  "`503 Service unavailable` itself.\n")
        code, text, _, _ = self.turn("astra", {"code": 1, "final.md": answer})
        self.assertEqual((code, text), (1, answer))
        self.sleep.assert_not_called()

    def test_a_word_moved_into_a_manifest_still_hands_over_or_waits(self):
        # a harness that never ran the turn hands it over at once, in its own manifest's words
        line = "The model gpt-nonexistent was not found. Try a different model."
        self.assertIn("was not found", stall("codex")["faults"])
        with self.assertRaises(run.CannotRun) as broken:
            self.turn("astra", {"code": 1, "stderr.log": f"{line}\n"})
        self.assertIn(line, str(broken.exception))
        self.sleep.assert_not_called()
        # ... unless the provider was down beside it, which is waited out on the same session
        self.assertIn("Can't reach the API server", stall("claude")["outages"])
        self.sleep.side_effect = None
        code, text, session, _ = self.turn(
            "opus", {"code": 1, "stderr.log": "error: unknown option '--effort'\n"
                                              "Can't reach the API server\n"}, DONE)
        self.assertEqual((code, session), (0, "s1"))
        self.assertIn("Done.", text)
        self.assertEqual(self.sleep.call_args_list, [((60,),)])
        # and an outage the harness put where the answer belongs is waited out as before
        self.assertIn("idle timeout", stall("codex")["outages"])
        self.sleep.reset_mock()
        code, text, _, _ = self.turn(
            "astra", {"code": 1, "final.md": "stream disconnected: idle timeout waiting for SSE"},
            DONE)
        self.assertEqual(code, 0)
        self.assertEqual(self.sleep.call_args_list, [((60,),)])
        self.assertEqual(self.marked, [])


if __name__ == "__main__":
    unittest.main()

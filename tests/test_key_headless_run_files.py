"""A worker's turn on Claude Code or Grok Build: the adapter's `run` verb starts the harness in the
workspace on the model and effort, hands it the prompt byte for byte, the conversation to resume
and, on Claude, the worker token, and leaves the files a run reads.

`run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]` hands the prompt over by
stdin or by a file, never as one argument, which Linux caps at 128 KiB.  Given a session id the
harness resumes it; given none it starts its own conversation, Grok's under a fresh UUID.  The
verb writes the harness's stdout to events.jsonl and its stderr to stderr.log, the last result
event's text to final.md and the last session id the events name to session_id, and exits with
the harness's own code.

Black-box: the adapter beside the program `AK_BIN` names, found as tests/fixtures/hookdrive.py
finds it, runs in a Home of tests/fixtures/akbin.py with a fake harness first on PATH under the
harness's own name.  This test fails against `/bin/false`.
"""

from collections import namedtuple
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

WORKSPACE = "code/acme"
EFFORT = "high"
CODE = 41       # no code ak exits with itself, so only the harness can hand it on
TOKEN = "sk-ant-oat01-acme"
SESSION = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d"     # the conversation a turn resumes
# Events of either harness's kind: two conversations and two results, each later one last.
EARLIER, LATER = "1f0e3a52-7c4b-4d8e-9a61-2b3c4d5e6f70", "6a7b8c9d-0e1f-4a2b-8c3d-4e5f6a7b8c9d"
FINAL = "## Summary\nfixed the parser"
EVENTS = [
    {"type": "system", "subtype": "init", "session_id": EARLIER},
    {"type": "result", "subtype": "success", "is_error": False, "result": "an earlier answer",
     "session_id": EARLIER},
    {"type": "system", "subtype": "init", "session_id": LATER},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Fixing it."}]}, "session_id": LATER},
    {"type": "result", "subtype": "success", "is_error": False, "result": FINAL,
     "session_id": LATER},
]
STDOUT = "".join(json.dumps(event) + "\n" for event in EVENTS).encode()
STDERR = "acme: a warning, ünïcødé\n".encode()
# Past what one argument holds, with what a shell or an option parser would take for its own.
# Neither prompt ends in one newline, which a shell's `$(...)` strips and a here-string puts back.
LONG = "".join(f"- step {n}: 'quotes', \"doubles\", $HOME, `ticks`, back\\slashes, ünïcødé\r\n"
               for n in range(2000)).encode() + b"done"
assert len(LONG) > 128 * 1024
SHORT = b"Fix the parser in acme.\n\n"

# The harness: it writes down its words, where it runs and its environment, keeps the prompt it
# reads from the file its words name after `flag`, or else from stdin, prints a few events and a
# warning, and exits with CODE.
FAKE = """#!{python}
import json, os, shutil, sys
words = sys.argv[1:]
os.mkdir({saw!r})
with open(os.path.join({saw!r}, "started.json"), "w") as started:
    json.dump({{"words": words, "cwd": os.getcwd(), "env": dict(os.environ)}}, started)
given = open(words[words.index({flag!r}) + 1], "rb") if {flag!r} else sys.stdin.buffer
with open(os.path.join({saw!r}, "prompt"), "wb") as prompt:
    shutil.copyfileobj(given, prompt)
sys.stdout.buffer.write({stdout!r})
sys.stderr.buffer.write({stderr!r})
sys.exit({code})
"""

# What one turn came to: the verb's exit code; the harness's words, where it ran under HOME, its
# environment and the prompt it got; and each file the verb left in its out-dir, None if none.
Turn = namedtuple("Turn", "code words cwd env prompt files")
FILES = ("events.jsonl", "stderr.log", "final.md", "session_id")


def turn(harness, prompt, session=None, token=None):
    """One `run` of the harness's adapter in a Home of its own, holding a worker token if given,
    as ak hands it one: the prompt in the out-dir, which is there already."""
    adapter = ROOT / "adapters" / f"{harness.harness}.sh"
    assert adapter.is_file(), f"no adapter at {adapter}"
    with Home() as home:
        saw = home.root / "saw"
        home.fake(harness.program, FAKE.format(
            python=sys.executable, saw=str(saw), flag=harness.prompt_flag, stdout=STDOUT,
            stderr=STDERR, code=CODE))
        if token:
            home.write(".agentkit/secrets/claude_oauth_token", f"{token}\n")    # as install.sh writes it
        workspace, out = home.path / WORKSPACE, home.path / "turn"
        workspace.mkdir(parents=True)
        out.mkdir()
        (out / "prompt.md").write_bytes(prompt)
        done = home.run(str(adapter), "run", harness.model, EFFORT, str(workspace),
                        str(out / "prompt.md"), str(out), *([session] if session else []))
        assert (saw / "started.json").is_file(), f"{harness.program} never started: {done.err}"
        started = json.loads((saw / "started.json").read_text())
        got = saw / "prompt"
        return Turn(done.code, started["words"], os.path.relpath(started["cwd"], home.path),
                    started["env"], got.read_bytes() if got.is_file() else None,
                    {name: (out / name).read_bytes() if (out / name).is_file() else None
                     for name in FILES})


class Turns:
    """Three turns of one harness: a new one with a long prompt and a worker token, another new
    one, and one resuming SESSION."""

    @classmethod
    def setUpClass(cls):
        cls.new = turn(cls, LONG, token=TOKEN)
        cls.again = turn(cls, SHORT)
        cls.resumed = turn(cls, SHORT, session=SESSION)
        cls.turns = {"new": (cls.new, LONG), "again": (cls.again, SHORT),
                     "resumed": (cls.resumed, SHORT)}

    def after(self, words, flag):
        self.assertIn(flag, words[:-1])
        return words[words.index(flag) + 1]

    def test_it_runs_in_the_workspace_on_the_model_and_effort(self):
        for name, (run, _) in self.turns.items():
            with self.subTest(turn=name):
                self.assertEqual(run.cwd, WORKSPACE)
                self.assertEqual(self.after(run.words, "--model"), self.model)
                self.assertEqual(self.after(run.words, self.effort_flag), EFFORT)

    def test_it_gets_the_prompt_byte_for_byte_one_past_128_kib_too(self):
        for name, (run, prompt) in self.turns.items():
            with self.subTest(turn=name):
                self.assertEqual(run.prompt, prompt)

    def test_a_turn_given_a_session_id_resumes_it(self):
        self.assertEqual(self.after(self.resumed.words, "--resume"), SESSION)
        if self.fresh_flag:
            self.assertNotIn(self.fresh_flag, self.resumed.words)

    def test_a_turn_without_one_starts_the_harness_s_own(self):
        for run in self.new, self.again:
            self.assertNotIn("--resume", run.words)
            self.assertNotIn("--continue", run.words)
        if self.fresh_flag:
            ids = [self.after(run.words, self.fresh_flag) for run in (self.new, self.again)]
            for given in ids:
                self.assertEqual(str(uuid.UUID(given)), given)
            self.assertNotEqual(*ids)

    def test_events_jsonl_and_stderr_log_hold_the_harness_s_output(self):
        for name, (run, _) in self.turns.items():
            with self.subTest(turn=name):
                self.assertEqual(run.files["events.jsonl"], STDOUT)
                self.assertEqual(run.files["stderr.log"], STDERR)

    def test_final_md_and_session_id_hold_the_last_result_and_session_the_events_name(self):
        # either may end its one line
        for name, (run, _) in self.turns.items():
            with self.subTest(turn=name):
                self.assertIn(run.files["final.md"], (FINAL.encode(), f"{FINAL}\n".encode()))
                self.assertIn(run.files["session_id"], (LATER.encode(), f"{LATER}\n".encode()))

    def test_the_verb_exits_with_the_harness_s_code(self):
        for name, (run, _) in self.turns.items():
            with self.subTest(turn=name):
                self.assertEqual(run.code, CODE)


class ClaudeCode(Turns, unittest.TestCase):
    harness, program, model = "claude", "claude", "claude-acme-7"
    effort_flag, prompt_flag, fresh_flag = "--effort", None, None

    def test_the_worker_token_reaches_it_where_ak_holds_one(self):
        self.assertEqual(self.new.env.get("CLAUDE_CODE_OAUTH_TOKEN"), TOKEN)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", self.again.env)


class GrokBuild(Turns, unittest.TestCase):
    harness, program, model = "grokbuild", "grok", "grok-acme-4"
    effort_flag, prompt_flag, fresh_flag = "--reasoning-effort", "--prompt-file", "--session-id"


if __name__ == "__main__":
    unittest.main()

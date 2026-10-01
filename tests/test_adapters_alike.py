"""Every harness takes its prompt the same way and hands back only its final answer.

A reviewer's prompt runs to 371 KB, and Linux refuses a single argument over 128 KiB: so
every adapter's `run` hands its harness the prompt from a file or stdin, never as one
word, and a 400 KB prompt starts on each.  A turn's saved answer is its last message on
every harness, OpenCode's included, never the narration a tool turn speaks between calls.

Offline: the real adapters against a temporary HOME, with one fake harness on PATH under
the name of every program the manifests name; it keeps its longest argument's length and
whatever prompt reached it.  No harness, no network.  The loop reads adapters/*.toml, so
a harness added later is covered the way these are.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = sorted((REPO / "adapters").glob("*.toml"))
ARG_MAX = 128 * 1024   # MAX_ARG_STRLEN: the longest single argument Linux will exec

# A harness that keeps, under $SEEN, the length in bytes of its longest argument and every
# prompt that reached it -- its stdin, and the file named after --prompt-file or --file --
# and then answers with $SEEN/events where there is one.  Only a turn is recorded: the
# calls an adapter makes around one (a session export, a version) answer nothing.
FAKE = """#!/usr/bin/env bash
export LC_ALL=C
case "${1:-}" in session|auth|models|--version) exit 0 ;; esac
longest=0 prev=""
for a in "$@"; do
  [ "${#a}" -gt "$longest" ] && longest=${#a}
  case $prev in --prompt-file|--file) cat -- "$a" >>"$SEEN/prompt" ;; esac
  prev=$a
done
echo "$longest" >"$SEEN/longest"
cat >>"$SEEN/prompt"
cat -- "$SEEN/events" 2>/dev/null
exit 0
"""

# An OpenCode tool turn as `opencode run --format json` streams it: a message that says what
# it is about to do, its call, and the message that answers.
TOOL_TURN = """\
{"type": "step_start", "sessionID": "ses_alike", "part": {"type": "step-start", "messageID": "msg_1"}}
{"type": "text", "sessionID": "ses_alike", "part": {"type": "text", "messageID": "msg_1", "text": "Let me run the tests first."}}
{"type": "tool_use", "sessionID": "ses_alike", "part": {"type": "tool", "messageID": "msg_1", "tool": "bash"}}
{"type": "step_finish", "sessionID": "ses_alike", "part": {"type": "step-finish", "messageID": "msg_1", "reason": "tool-calls"}}
{"type": "step_start", "sessionID": "ses_alike", "part": {"type": "step-start", "messageID": "msg_2"}}
{"type": "text", "sessionID": "ses_alike", "part": {"type": "text", "messageID": "msg_2", "text": "## Summary\\nAll green."}}
{"type": "step_finish", "sessionID": "ses_alike", "part": {"type": "step-finish", "messageID": "msg_2", "reason": "stop"}}
"""


class AdaptersAlike(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-adapters-alike-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        fakes = self.root / "bin"
        fakes.mkdir()
        (fakes / "harness").write_text(FAKE)
        (fakes / "harness").chmod(0o755)
        # the program each adapter runs, as its manifest's `[update] version` names it
        self.programs = {}
        for path in MANIFESTS:
            program = tomllib.loads(path.read_text())["update"]["version"][0]
            (fakes / program).symlink_to("harness")
            self.programs[path.stem] = program
        self.assertGreaterEqual(set(self.programs), {"antigravity", "claude", "codex",
                                                     "grokbuild", "muse", "opencode"})
        # nothing of the caller's reaches a turn: not its login, its account or its seat
        path = os.pathsep.join(dict.fromkeys(
            (str(fakes), os.path.dirname(sys.executable), "/usr/bin", "/bin")))
        self.env = {"HOME": str(self.home), "PATH": path, "AGENTKIT_SESSION": ""}

    def turn(self, harness, prompt, events=None):
        """One worker turn through that adapter: (process, what the fake kept, out dir)."""
        seen = self.root / f"seen-{harness}"
        seen.mkdir()
        if events is not None:
            (seen / "events").write_text(events)
        pf = self.root / f"prompt-{harness}.md"
        pf.write_text(prompt)
        out = self.root / f"out-{harness}"
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "run", "test-model",
                               "high", str(self.ws), str(pf), str(out)],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env={**self.env, "SEEN": str(seen)}, timeout=120)
        return proc, seen, out

    def test_a_400_kb_prompt_starts_on_every_adapter(self):
        head, tail = "REVIEW-PROMPT-START\n", "\nREVIEW-PROMPT-END\n"
        prompt = head + "r" * (400 * 1024 - len(head) - len(tail)) + tail
        self.assertEqual(len(prompt.encode()), 400 * 1024)
        for harness in self.programs:
            with self.subTest(harness=harness):
                proc, seen, _ = self.turn(harness, prompt)
                # an argument over the limit fails the exec itself: the fake never runs
                self.assertTrue((seen / "longest").exists(),
                                f"{harness} never started its harness: {proc.stderr}")
                self.assertLessEqual(int((seen / "longest").read_text()), ARG_MAX, harness)
                self.assertEqual((seen / "prompt").read_text(), prompt,
                                 f"{harness} did not hand over the prompt whole")
                self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")

    def test_opencode_saves_the_turn_s_last_message(self):
        proc, _, out = self.turn("opencode", "Run the tests.\n", TOOL_TURN)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((out / "final.md").read_text(), "## Summary\nAll green.\n")
        self.assertEqual((out / "session_id").read_text(), "ses_alike")


if __name__ == "__main__":
    unittest.main(verbosity=2)

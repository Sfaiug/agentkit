"""A prompt of any size reaches an OpenCode worker, and a worker that never starts hands over.

Offline and deterministic: a fake `opencode` on PATH records its argv and the
whole of every `--file` attachment, every HOME is a temporary directory, and the
126 handover is a mocked worker turn with an empty event stream. Nothing here
contacts a provider or the real CLI.
"""

import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run  # noqa: E402

ADAPTER = str(REPO / "adapters/opencode.sh")

FAKE = """#!/usr/bin/env bash
# Fake opencode for tests/test_opencode_large_prompt.py: every argv lands in
# $FAKE_ARGV, and every --file/-f attachment whole in $FAKE_GOT, its path in
# $FAKE_FILES.  `run` then cats $FAKE_EVENTS and exits $FAKE_RC.
[ -n "${FAKE_ARGV:-}" ] && printf '%s\\n' "$*" >>"$FAKE_ARGV"
if [ "$1" = run ]; then
  prev=""
  for a in "$@"; do
    if [ "$prev" = "--file" ] || [ "$prev" = "-f" ]; then
      [ -n "${FAKE_GOT:-}" ] && cat -- "$a" >>"$FAKE_GOT" 2>/dev/null
      [ -n "${FAKE_FILES:-}" ] && printf '%s\\n' "$a" >>"$FAKE_FILES"
    fi
    prev=$a
  done
  for a in "$@"; do
    case "$a" in --file=*)
      p=${a#--file=}
      [ -n "${FAKE_GOT:-}" ] && cat -- "$p" >>"$FAKE_GOT" 2>/dev/null
      [ -n "${FAKE_FILES:-}" ] && printf '%s\\n' "$p" >>"$FAKE_FILES"
      ;;
    esac
  done
  cat -- "${FAKE_EVENTS:-/dev/null}" 2>/dev/null
  exit "${FAKE_RC:-0}"
fi
case "$1" in
  session) cat -- "${FAKE_EXPORT:-/dev/null}" 2>/dev/null ;;
  auth) printf '%s' "${FAKE_AUTH_LIST:-[]}" ;;
  --version) echo "opencode v9.9.9-test" ;;
  *) echo "fake opencode: $*" >&2; exit 2 ;;
esac
"""

EVENTS = ('{"type": "text", "sessionID": "ses_large", '
          '"part": {"type": "text", "text": "done"}}\n')


class LargePrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".opencode-large-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "opencode").write_text(FAKE)
        (self.bin / "opencode").chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                    "AGENTKIT_SESSION": ""}
        self.argv = self.root / "argv.log"
        self.got = self.root / "got.md"
        self.files = self.root / "files.log"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "large-test",
            "TMUX_TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}))
        config.ensure_dirs()
        self.cfg = config.load()

    def adapter_run(self, prompt_text):
        import subprocess
        ws = self.root / "ws"
        ws.mkdir(exist_ok=True)
        prompt = self.root / "prompt.md"
        prompt.write_text(prompt_text)
        out = self.root / "out"
        events = self.root / "events.jsonl"
        events.write_text(EVENTS)
        env = dict(self.env, FAKE_ARGV=str(self.argv), FAKE_GOT=str(self.got),
                   FAKE_FILES=str(self.files), FAKE_EVENTS=str(events),
                   FAKE_EXPORT=str(self.root / "missing.json"))
        proc = subprocess.run([ADAPTER, "run", "mimo/mimo-v2.6-pro", "none",
                               str(ws), str(prompt), str(out)],
                              capture_output=True, text=True, env=env)
        return proc, prompt

    def test_a_300_kib_prompt_reaches_the_fake_whole(self):
        head, tail = "LARGE-PROMPT-START\n", "\nLARGE-PROMPT-END"
        body = head + "x" * (300 * 1024 - len(head) - len(tail)) + tail
        self.assertEqual(len(body.encode()), 300 * 1024)
        proc, _ = self.adapter_run(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.argv.read_text()
        self.assertIn("--file", argv)
        # the attachment is the prompt whole, and the message is short: the
        # 300 KiB never went through argv, which Linux refuses over 128 KiB
        self.assertEqual(self.got.read_bytes(), body.encode())
        self.assertLess(len(argv), 20000)
        self.assertNotIn(body[:500], argv)

    def test_a_2_kib_prompt_goes_as_the_message(self):
        head, tail = "SMALL-PROMPT-START\n", "\nSMALL-PROMPT-END"
        body = head + "y" * (2 * 1024 - len(head) - len(tail)) + tail
        self.assertEqual(len(body.encode()), 2 * 1024)
        proc, _ = self.adapter_run(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.argv.read_text()
        self.assertNotIn("--file", argv)
        self.assertIn(body, argv)
        self.assertFalse(self.got.exists() and self.got.stat().st_size)

    def worker(self, answers):
        """A fake worker.call playing `answers` back: (code, text, session, stderr) each."""
        calls = []

        def call(*args, **kwargs):
            code, text, session, *stderr = answers[min(len(calls), len(answers) - 1)]
            calls.append(args)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "prompt.md").write_text("You are the executor.\n")
            (out / "final.md").write_text(text)
            (out / "stderr.log").write_text("".join(stderr))
            (out / "events.jsonl").write_text("")
            (out / "session_id").write_text(session)
            return code, text, session, False

        return calls, call

    def test_exit_126_with_an_empty_stream_hands_over_instead_of_waiting(self):
        from types import SimpleNamespace
        line = "opencode: Argument list too long"
        calls, fake = self.worker([(126, "", "", f"{line}\n"),
                                   (0, "## Summary\nDone elsewhere.\n", "s2")])
        lp = SimpleNamespace(cfg=self.cfg, state={"executor": "opus"}, executor="opus",
                             exec_sid=None, wt=self.root, turn_limit=60, rnd=1,
                             dir=lambda name: self.root / "round-1" / name,
                             role=lambda role: role, save=lambda: None, log=lambda _: None)
        handed = []

        def hand(lp, why, detail, dry):
            handed.append((lp.executor, why, detail))
            lp.executor, lp.exec_sid = "astra", None
            return "astra"

        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep",
                             side_effect=AssertionError("transient wait")), \
                patch.object(run, "hand_executor", side_effect=hand):
            summary = run.execute(lp, "executor", "Do the task.", "executor")
        self.assertIn("Done elsewhere.", summary)
        self.assertEqual(len(handed), 1)
        self.assertEqual(handed[0][0], "opus")
        self.assertIn(line, handed[0][2])
        self.assertEqual([args[1] for args in calls], ["opus", "astra"])


if __name__ == "__main__":
    unittest.main()

"""ak compacts no seat: one idle a day after a turn on 900,000 tokens is typed nothing.

Claude Code compacts an idle seat itself, and two compactors on one seat can only clash
(AGENTS.md's owner rules).  ak's seat wrapper once typed the harness's compact command into such
a seat, at its prompt after five seconds of quiet, polling every five.  The seat here is one a
person opened with `ak orch`, so its pane runs whatever ak puts around a harness, and the harness
is a stand-in `claude`: its conversation, as Claude Code keeps it, ended a day ago on 900,000
tokens, and it says so too where the old wrapper asked (IDLE_COMPACT_STATE).  It sits at its
prompt keeping every byte that reaches it, through a tick of `ak watch` and well past that quiet.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and a
person's terminal from akterm.py.  The seat's wrapper names its pane through the socket path
tmux gave it, so this Home's tmux takes a socket path inside the Home's own directory; and the
tick runs with a /tmp of its own, since a tick may start collection, which sweeps /tmp.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import FIXTURES
from fixtures.akterm import Terminal

QUIET = 12      # seconds at the prompt: past the old wrapper's quiet and its next poll
# The Home's own guard, but a socket path inside this Home's directory goes through.
TMUX = """#!/bin/sh
skip=
for a do
  if [ -n "$skip" ]; then
    if [ "$skip" = S ]; then
      case $a in {dir}/*) ;; *) echo "tmux: not this Home's server" >&2; exit 2 ;; esac
    fi
    skip=; continue
  fi
  case $a in
    -S) skip=S ;;
    -S*) echo "tmux: not this Home's server" >&2; exit 2 ;;
    -[cfLT]) skip=1 ;;
    -*) ;;
    *) break ;;
  esac
done
export TMUX_TMPDIR={dir}
exec {real} "$@"
"""
HARNESS = r"""
import json, os, re, select, sys, time, tty
screen, report, release, *args = sys.argv[1:]
session = args[args.index("--session-id") + 1] if "--session-id" in args else "acme"
ended = time.time() - 86400
folder = os.path.join(os.environ["HOME"], ".claude/projects", re.sub(r"[^A-Za-z0-9]", "-",
                                                                     os.getcwd()))
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, session + ".jsonl"), "w") as fh:
    fh.write(json.dumps({
        "type": "assistant", "sessionId": session,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ended)),
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}],
                    "usage": {"input_tokens": 900000, "output_tokens": 12}}}) + "\n")
if os.environ.get("IDLE_COMPACT_STATE"):
    with open(os.environ["IDLE_COMPACT_STATE"], "w") as fh:
        json.dump({"ts": ended, "context_tokens": 900000, "session_id": session,
                   "pid": os.getpid(), "pids": [os.getpid()]}, fh)
tty.setraw(0)
os.write(1, open(screen, "rb").read().replace(b"\n", b"\r\n"))
typed, drawn = bytearray(), time.monotonic()
while not (os.path.exists(release) and time.monotonic() - drawn > float(os.environ["QUIET"])):
    if select.select([0], [], [], 0.05)[0]:
        typed.extend(os.read(0, 65536))
with open(report + ".part", "wb") as fh:
    fh.write(typed)
os.rename(report + ".part", report)
"""


@unittest.skipUnless(REAL_TMUX and shutil.which("bwrap"), "needs tmux and bwrap")
class IdleSeat(unittest.TestCase):
    def test_a_seat_idle_long_on_a_large_context_is_typed_nothing(self):
        home = Home()
        self.addCleanup(home.close)
        home.fake("tmux", TMUX.replace("{dir}", shlex.quote(str(home.tmux_dir)))
                  .replace("{real}", shlex.quote(REAL_TMUX)))
        harness, report, release = (home.root / name for name in ("harness.py", "typed", "go"))
        harness.write_text(HARNESS)
        home.fake("claude", f"#!/bin/sh\nQUIET={QUIET} exec " + shlex.join([
            sys.executable, "-I", str(harness), str(FIXTURES / "claude-prompt-pane.txt"),
            str(report), str(release)]) + ' "$@"\n')
        # the weekly audit would open a seat of its own on the tick
        config = home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        cwd = home.path / "code/acme"
        cwd.mkdir(parents=True)
        term = Terminal(home, "orch", "acme", "--model", "opus", "--workers", "opus",
                        size=(100, 40))
        term.wait("bypass permissions on")
        tick = home.run("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
                        "--bind", str(home.root), str(home.root),
                        "--bind", str(home.tmux_dir), str(home.tmux_dir), "--", AK, "watch")
        self.assertEqual(tick.code, 0, tick.out + tick.err)
        release.touch()
        term.wait(lambda _: report.exists(), bound=QUIET + 60)
        self.assertEqual(report.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()

"""ak compacts no seat itself: each harness's own compaction does.

Offline: no adapter manifest has a `[compact]` table; a seat's wrapper, run under a pty around
a fake harness with a fake tmux on PATH, types nothing into that harness however long ago its
turn ended and however large its context, and still reads the seat's pane once its screen comes
to rest.  The fake harness reports, wherever its wrapper asks (`IDLE_COMPACT_STATE`, the hook's
stamp before), a turn that ended a day ago on 900,000 tokens: the wrapper from before typed
`/compact` at its next poll.  And a seat started before keeps that wrapper, so a turn's end
stamps nothing for it to poll, and an update (install.sh) takes away every stamp left.
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config  # noqa: E402

WRAPPER = REPO / "tools/idle-compact.py"
QUIET = 12      # seconds the harness sits at its prompt: past the old wrapper's poll and quiet

# Writes every call down with its time; a capture is answered with a prompt pane.
FAKE_TMUX = '''#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_TMUX_LOG"], "a") as log:
    log.write(json.dumps({"at": time.time(), "args": sys.argv[1:]}) + "\\n")
if "capture-pane" in sys.argv:
    sys.stdout.write(open(os.environ["FAKE_PANE"]).read())
'''

# A turn's last frames, its prompt, then QUIET seconds at that prompt recording every byte that
# reaches it.
FAKE_HARNESS = '''#!/usr/bin/env python3
import json, os, select, sys, time, tty
tty.setraw(0)
stamp = os.environ.get("IDLE_COMPACT_STATE")
if stamp:
    with open(stamp, "w") as handle:
        json.dump({"ts": time.time() - 86400, "context_tokens": 900000, "session_id": "acme",
                   "pid": os.getpid(), "pids": [os.getpid()]}, handle)
for frame in range(5):
    sys.stdout.write(f"frame {frame}\\r\\n")
    sys.stdout.flush()
    time.sleep(0.1)
sys.stdout.write("> ")
sys.stdout.flush()
with open(os.environ["DRAWN"], "w") as handle:
    handle.write(repr(time.time()))
typed = bytearray()
until = time.monotonic() + float(os.environ["QUIET"])
while time.monotonic() < until:
    if select.select([0], [], [], 0.05)[0]:
        typed.extend(os.read(0, 65536))
with open(os.environ["TYPED"], "wb") as handle:
    handle.write(typed)
'''


class Manifests(unittest.TestCase):
    def test_no_adapter_declares_a_compact_table(self):
        for path in sorted((REPO / "adapters").glob("*.toml")):
            with self.subTest(harness=path.stem):
                table = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertFalse("compact" in table, f"{path.name} has a [compact] table")


class Seat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-no-compact-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text(FAKE_TMUX)
        (bin_dir / "tmux").chmod(0o755)
        self.harness = self.root / "harness.py"
        self.harness.write_text(FAKE_HARNESS)
        state = self.root / ".agentkit" / config.STATE.relative_to(config.HOME)
        state.mkdir(parents=True)
        # its hooks say its turn ended, and its word was already decided from what the pane
        # reads, so a look at it is one capture and nothing more
        (state / "hook-acme.json").write_text(json.dumps(
            {"session": "acme", "event": "Stop", "kind": "", "text": "", "at": 1.0}))
        (state / "seat-acme.json").write_text(json.dumps(
            {"word_from": ["at_prompt", "prompt.composer", ""]}))
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("AGENTKIT_", "AK_", "IDLE_COMPACT_", "TMUX"))}
        self.env.update(HOME=str(self.root), PATH=f"{bin_dir}{os.pathsep}{self.env['PATH']}",
                        XDG_DATA_HOME=str(self.root / "share"), AGENTKIT_SESSION="acme",
                        TMUX=f"{self.root / 'sock'},1,0", TMUX_PANE="%5",
                        AGENTKIT_TMUX_SOCKET="agentkit-test", TMUX_TMPDIR=str(self.root),
                        FAKE_TMUX_LOG=str(self.root / "tmux.jsonl"),
                        FAKE_PANE=str(REPO / "tests/fixtures/claude-prompt-pane.txt"),
                        DRAWN=str(self.root / "drawn"), TYPED=str(self.root / "typed"),
                        QUIET=str(QUIET))

    def test_a_seat_idle_long_on_a_large_context_is_typed_nothing_and_looked_at_at_rest(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, str(WRAPPER), "--harness", "claude", "--",
             sys.executable, str(self.harness)],
            stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=self.env, cwd=str(self.root))
        os.close(slave)
        self.addCleanup(proc.kill)
        try:
            while proc.poll() is None:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        if not os.read(master, 65536):
                            break
                    except OSError:
                        break
        finally:
            os.close(master)
        status, stderr = proc.wait(timeout=30), proc.stderr.read().decode()
        proc.stderr.close()
        self.assertEqual((self.root / "typed").read_bytes(), b"")
        drawn = float((self.root / "drawn").read_text())
        calls = [json.loads(line) for line in
                 (self.root / "tmux.jsonl").read_text().splitlines() if line]
        rested = [call for call in calls
                  if "capture-pane" in call["args"] and call["at"] > drawn]
        self.assertTrue(rested, calls)
        self.assertEqual(status, 0, stderr)


class OlderWrappers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-no-compact-old-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.stamps = Path(tmp.name) / ".agentkit" / "state" / "idle-compact"
        self.stamps.mkdir(parents=True)

    def test_a_turn_end_stamps_nothing(self):
        stamp = self.stamps / "acme-4242.json"
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("AGENTKIT_", "AK_", "TMUX"))}
        env.update(HOME=str(self.stamps.parents[2]), IDLE_COMPACT_STATE=str(stamp))
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "acme",
                              "context_tokens": 900000})
        proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], input=payload,
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(stamp.exists())

    def test_an_update_takes_away_every_stamp_an_idle_seats_wrapper_polls(self):
        """No hook event has to come first: a seat idle since before the update has none."""
        for name in ("acme-4242.json", "4243.json"):     # a named seat's, an unnamed one's
            (self.stamps / name).write_text(json.dumps(
                {"ts": time.time(), "context_tokens": 900000, "pid": 4242, "pids": [4242]}))
        (self.stamps / "log").write_text("")
        source = (REPO / "install.sh").read_text()
        begin = source.index("# A seat started before ak stopped compacting seats")
        block = source[begin:source.index("\n", source.index("idle-compact/", begin))]
        for run in ("with stamps", "with none left"):
            with self.subTest(run=run):
                proc = subprocess.run(
                    ["bash", "-c", f"set -euo pipefail\nAK={shlex.quote(str(self.stamps.parents[1]))}\n{block}"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual([path.name for path in self.stamps.iterdir()], ["log"])


if __name__ == "__main__":
    unittest.main()

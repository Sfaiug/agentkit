"""The one auto-compaction every orchestrator seat gets, whatever harness it runs.

Offline and deterministic: tools/idle-compact.py is run under a pty around a fake harness --
a small script that prints a prompt, ends a turn the way its real harness does, and writes down
everything typed into it -- with the real adapters/<harness>.toml deciding what is typed.  No
harness, no network and no tmux is involved.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import fcntl
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch

WRAPPER = REPO / "tools/idle-compact.py"
HOOK = REPO / "hooks/seat-state.sh"
IDLE = 2.0            # the flags every seat here runs under: the real 2400 s / 40000 tokens
POLL = 0.5            # rule, scaled down to something a test can wait out
FLOOR = 1
DEADLINE = 5.0        # how long after a turn's end a seat has to have compacted itself

# A harness for the wrapper to sit around.  It says a turn ended the way its own signal says it
# -- a state-file stamp naming the pid the wrapper expects, or just the prompt its manifest's
# at-the-prompt rule matches -- and records every byte that reaches it, with the time.
FAKE = '''#!/usr/bin/env python3
import json, os, select, signal, sys, time

record = open(os.environ["FAKE_RECORD"], "a", buffering=1)
prompt = os.environ.get("FAKE_PROMPT", "> ")
tokens = int(os.environ.get("FAKE_TOKENS", "0"))
claim = int(os.environ.get("FAKE_PID", "0")) or os.getpid()
life = float(os.environ.get("FAKE_LIFE", "10"))
stop_on = os.environ.get("FAKE_STOP_ON", "")


def note(event, **fields):
    record.write(json.dumps({"at": time.time(), "event": event, **fields}) + "\\n")


def turn_end():
    sys.stdout.write(prompt + "\\n")
    sys.stdout.flush()
    path = os.environ.get("IDLE_COMPACT_STATE")
    if path and os.environ.get("FAKE_SIGNAL", "hook") == "hook":
        with open(path + ".tmp", "w") as handle:
            json.dump({"ts": time.time(), "context_tokens": tokens, "session_id": "fake",
                       "pid": claim, "pids": [claim]}, handle)
        os.replace(path + ".tmp", path)
    note("turn_end")


def repaint(_signum, _frame):
    os.write(1, b"R" * 2048)
    note("repaint")


if os.environ.get("FAKE_MUSE_SESSION"):
    # what Muse itself writes: who opened this session, and what the last turn sent
    directory = os.path.join(os.environ["XDG_DATA_HOME"], "muse/sessions/2026/09/14/fake")
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "session.jsonl"), "w") as handle:
        handle.write(json.dumps({"payload": {
            "kind": "route_facts", "record": {"pid": claim, "cwd": os.getcwd()}}}) + "\\n")
        handle.write(json.dumps({"payload": {"event": {
            "kind": "goal_usage_attribution",
            "record": {"usage_family": "provider", "owner": {"owner_type": "main_root"},
                       "quantity": {"input_tokens": tokens}}}}}) + "\\n")

if os.environ.get("FAKE_REPAINT"):
    signal.signal(signal.SIGWINCH, repaint)
turn_end()
born = time.monotonic()
deadline = born + life
redraw = float(os.environ.get("FAKE_REDRAW", "0"))
typed = ""
while time.monotonic() < deadline:
    if redraw and time.monotonic() - born >= redraw:
        redraw = 0.0
        sys.stdout.write(prompt + "\\n")   # the composer again, no turn behind it
        sys.stdout.flush()
        note("redraw")
    ready, _, _ = select.select([0], [], [], 0.05)
    if not ready:
        continue
    try:
        data = os.read(0, 65536)
    except OSError:
        break
    if not data:
        break
    text = data.decode("utf-8", "replace")
    typed += text
    note("typed", data=text)
    if "TURN" in typed:
        typed = ""
        turn_end()
    elif stop_on and stop_on in typed:
        break
note("exit")
'''


def manifest_command(harness):
    """What that harness's own adapter says compacts it -- never a copy of it kept here."""
    keys = config.manifest(harness)["compact"]["command"]
    return keys if isinstance(keys, str) else "".join(keys)


def case_body(adapter, verb):
    """One verb's branch of an adapter's case statement, and nothing of its neighbours'."""
    text = (REPO / "adapters" / adapter).read_text()
    start = re.search(rf"^{re.escape(verb)}\)$", text, re.M)
    assert start, f"{adapter} has no {verb}) branch"
    rest = text[start.end():]
    end = re.search(r"^[\w*-]+\)$", rest, re.M)
    return rest[:end.start()] if end else rest


class Seat(unittest.TestCase):
    """A wrapped seat, run for real under a pty with a fake harness inside it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5e-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.harness = self.root / "fake-harness.py"
        self.harness.write_text(FAKE)
        self.harness.chmod(0o755)
        self.seats = 0

    def env(self, record, **extra):
        env = {key: value for key, value in os.environ.items()
               if key not in ("IDLE_COMPACT_STATE", "AGENTKIT_SESSION", "AGENTKIT_ADAPTER_DIR",
                              "XDG_DATA_HOME", "AK_RUN_ROLE")}
        env.update(HOME=str(self.root), FAKE_RECORD=str(record),
                   XDG_DATA_HOME=str(self.root / "share"))
        env.update({key: str(value) for key, value in extra.items()})
        return env

    def run_seat(self, *flags, script=(), limit=20.0, **fake):
        """Run the wrapper around the fake harness, playing `script` at its due seconds.

        Returns (stderr text, the harness's record of what happened).  The pty is the seat's
        terminal, so a resize on it is a resize of the seat.
        """
        self.seats += 1
        record = self.root / f"typed-{self.seats}.jsonl"
        record.write_text("")
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        command = [sys.executable, str(WRAPPER), "--idle", str(IDLE), "--poll", str(POLL),
                   "--min-context", str(FLOOR), *flags, "--", sys.executable, str(self.harness)]
        proc = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                env=self.env(record, **fake), cwd=str(self.root))
        os.close(slave)
        self.addCleanup(proc.kill)
        steps = sorted(script, key=lambda step: step[0])
        started = time.monotonic()
        try:
            while True:
                now = time.monotonic() - started
                if steps and now >= steps[0][0]:
                    steps.pop(0)[1](self, proc, master)
                    continue
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        if not os.read(master, 65536):
                            break
                    except OSError:
                        break
                elif proc.poll() is not None:
                    break
                if now > limit:
                    proc.kill()
                    break
        finally:
            os.close(master)
        stderr = proc.stderr.read().decode("utf-8", "replace")
        proc.stderr.close()
        proc.wait(timeout=10)
        events = [json.loads(line) for line in record.read_text().splitlines() if line]
        return stderr, events

    # --- reading the harness's record --------------------------------------

    def typed(self, events):
        return "".join(event["data"] for event in events if event["event"] == "typed")

    def compacted_after(self, events, command):
        """Seconds from the last turn end before that command was typed, or None."""
        turn = None
        seen = ""
        for event in events:
            if event["event"] == "turn_end":
                turn, seen = event["at"], ""
            elif event["event"] == "typed":
                seen += event["data"]
                if command.rstrip("\r\n") in seen and turn is not None:
                    return event["at"] - turn
        return None

    def assert_compacted(self, events, command):
        """That harness's own command was typed, within the deadline of its turn ending."""
        self.assertIn(command.rstrip("\r"), self.typed(events), events)
        elapsed = self.compacted_after(events, command)
        self.assertIsNotNone(elapsed, events)
        self.assertLess(elapsed, DEADLINE, events)
        return elapsed

    # --- (a) the seat every other one is modelled on ------------------------

    def test_v5e_a_claude_like_seat_compacts_itself_at_a_quiet_prompt(self):
        command = manifest_command("claude")
        _, events = self.run_seat(FAKE_TOKENS=40000, FAKE_STOP_ON="/compact", FAKE_LIFE=15)
        self.assert_compacted(events, command)

    # --- (b) whose state it is ---------------------------------------------

    def test_v5e_b_state_written_for_another_pid_never_compacts_the_seat(self):
        _, events = self.run_seat(FAKE_TOKENS=40000, FAKE_PID=999999, FAKE_LIFE=6)
        self.assertEqual(self.typed(events), "", events)
        log = (self.root / ".agentkit/state/idle-compact/log").read_text()
        self.assertIn("ignored state written for pid=999999", log)

    # --- (c) the floor ------------------------------------------------------

    def test_v5e_c_a_context_below_the_floor_never_compacts_the_seat(self):
        _, events = self.run_seat(FAKE_TOKENS=0, FAKE_LIFE=6)
        self.assertEqual(self.typed(events), "", events)

    # --- (d) a repaint is not the seat doing anything -----------------------

    def test_v5e_d_a_resize_and_its_repaint_do_not_defer_the_compaction(self):
        def resize(test, proc, master):
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.kill(proc.pid, signal.SIGWINCH)

        command = manifest_command("claude")
        _, quiet = self.run_seat(FAKE_TOKENS=40000, FAKE_STOP_ON="/compact", FAKE_LIFE=15)
        _, events = self.run_seat(script=[(1.0, resize)], FAKE_TOKENS=40000, FAKE_REPAINT=1,
                                  FAKE_STOP_ON="/compact", FAKE_LIFE=15)
        self.assertTrue(any(event["event"] == "repaint" for event in events), events)
        elapsed = self.assert_compacted(events, command)
        # ... and the 2 KB the resize made it draw bought it no time at all: the same seat with
        # nothing to repaint is the control, and both land on the same poll of the same grid
        self.assertLess(elapsed, self.compacted_after(quiet, command) + POLL / 2, (quiet, events))

    # --- (e) the owner is in the seat ---------------------------------------

    def test_v5e_e_owner_input_blocks_the_compaction_until_the_next_turn_ends(self):
        def types(test, proc, master):
            os.write(master, b"x")

        def ends_a_turn(test, proc, master):
            os.write(master, b"TURN\r")

        command = manifest_command("claude")
        _, events = self.run_seat(script=[(0.5, types), (5.0, ends_a_turn)],
                                  FAKE_TOKENS=40000, FAKE_STOP_ON="/compact", FAKE_LIFE=15)
        turns = [event for event in events if event["event"] == "turn_end"]
        self.assertEqual(len(turns), 2, events)
        # nothing was typed against the first turn, which the owner's `x` came after
        typed_before = [event for event in events
                        if event["event"] == "typed" and event["at"] < turns[1]["at"]]
        self.assertNotIn("/compact", "".join(event["data"] for event in typed_before))
        self.assert_compacted(events, command)

    # --- (f) the half of it that lives in the hook --------------------------

    def test_v5e_f_the_hook_stamps_time_tokens_and_pid_and_never_a_zero(self):
        state = self.root / "state.json"
        transcript = self.root / "transcript.jsonl"
        usage = {"input_tokens": 1000, "cache_read_input_tokens": 41000,
                 "cache_creation_input_tokens": 500}
        transcript.write_text("\n".join(
            [json.dumps({"type": "assistant", "message": {"usage": usage}})]
            + [json.dumps({"type": "user", "message": {"content": "tool result"}})] * 500) + "\n")
        environment = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                       "AGENTKIT_SESSION": "seat", "IDLE_COMPACT_STATE": str(state)}
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "one",
                              "transcript_path": str(transcript)})
        subprocess.run(["bash", str(HOOK)], input=payload.encode(), env=environment, check=True)
        written = json.loads(state.read_text())
        self.assertEqual(written["context_tokens"], 42500)
        self.assertGreater(written["ts"], time.time() - 60)
        self.assertIsInstance(written["pid"], int)
        self.assertIn(written["pid"], written["pids"])
        # the v4y seat-state record is the other half of this hook and is untouched by any of it
        fact = json.loads((self.root / ".agentkit/state/hook-seat.json").read_text())
        self.assertEqual((fact["session"], fact["event"]), ("seat", "Stop"))

        # a transcript with no usage in it -- and one truncated line -- says nothing rather
        # than zero, so the last good stamp stands
        empty = self.root / "empty.jsonl"
        empty.write_text(json.dumps({"type": "user"}) + "\n" + '{"truncated\n')
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "two",
                              "transcript_path": str(empty)})
        subprocess.run(["bash", str(HOOK)], input=payload.encode(), env=environment, check=True)
        self.assertEqual(json.loads(state.read_text())["session_id"], "one")

    # --- (g) the seat says so -----------------------------------------------

    def test_v5e_g_a_compacted_seat_records_when_it_last_compacted(self):
        self.run_seat(FAKE_TOKENS=40000, FAKE_STOP_ON="/compact", FAKE_LIFE=15,
                      AGENTKIT_SESSION="seat")
        written = json.loads((self.root / ".agentkit/state/compact-seat.json").read_text())
        self.assertEqual((written["session"], written["harness"]), ("seat", "claude"))
        self.assertEqual(written["context_tokens"], 40000)
        self.assertGreater(written["last_compact_at"], time.time() - 60)

    # --- (h) and (i) the same rule, on the other two harnesses --------------

    def test_v5e_h_a_codex_like_seat_compacts_on_its_own_command(self):
        command = manifest_command("codex")
        _, events = self.run_seat("--harness", "codex", FAKE_TOKENS=40000,
                                  FAKE_STOP_ON=command.rstrip("\r"), FAKE_LIFE=15)
        self.assert_compacted(events, command)

    def test_v5e_i_a_muse_like_seat_compacts_off_its_own_prompt_rule(self):
        command = manifest_command("muse")
        prompt = "muse-fake-1.0 · high · /tmp/seat · YOLO"
        _, events = self.run_seat("--harness", "muse", FAKE_SIGNAL="screen", FAKE_PROMPT=prompt,
                                  FAKE_MUSE_SESSION=1, FAKE_TOKENS=40000,
                                  FAKE_STOP_ON=command.rstrip("\r"), FAKE_LIFE=15)
        self.assert_compacted(events, command)

    def test_v5e_i_a_screen_read_seat_never_compacts_over_a_half_typed_line(self):
        """A composer redrawn around what the owner is typing is not the end of a turn."""
        def types(test, proc, master):
            os.write(master, b"x")

        prompt = "muse-fake-1.0 · high · /tmp/seat · YOLO"
        # the seat's tty echoes the character, so the composer is no longer the last thing
        # painted; a second later the harness redraws it around what is being typed
        _, events = self.run_seat("--harness", "muse", script=[(1.5, types)],
                                  FAKE_SIGNAL="screen", FAKE_PROMPT=prompt, FAKE_REDRAW=2.5,
                                  FAKE_MUSE_SESSION=1, FAKE_TOKENS=40000, FAKE_LIFE=9)
        self.assertEqual(len([e for e in events if e["event"] == "turn_end"]), 1, events)
        self.assertTrue(any(e["event"] == "redraw" for e in events), events)
        self.assertNotIn("/compact", self.typed(events))

    def test_v5e_i_a_harness_with_no_compact_command_is_told_so_and_never_typed_into(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "plain.toml").write_text('version = 1\n[compact]\ncommand = "none"\n')
        stderr, events = self.run_seat("--harness", "plain", FAKE_TOKENS=40000, FAKE_LIFE=5,
                                       AGENTKIT_ADAPTER_DIR=str(adapters))
        self.assertIn("plain has no compact command", stderr)
        self.assertEqual(self.typed(events), "", events)

    def test_v5e_i_a_harness_that_reports_no_context_size_is_told_so_and_never_typed_into(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "blind.toml").write_text(
            'version = 1\n[compact]\ncommand = "/compact\\r"\nsignal = "hook"\n')
        stderr, events = self.run_seat("--harness", "blind", FAKE_TOKENS=40000, FAKE_LIFE=5,
                                       AGENTKIT_ADAPTER_DIR=str(adapters))
        self.assertIn("blind does not report context size", stderr)
        self.assertEqual(self.typed(events), "", events)

    # --- (j) a worker is not a seat -----------------------------------------

    def test_v5e_j_no_headless_run_is_ever_wrapped(self):
        for adapter in ("claude.sh", "codex.sh", "muse.sh"):
            with self.subTest(adapter=adapter):
                self.assertNotIn("idle-compact.py", case_body(adapter, "run"))
                self.assertIn("idle-compact.py", case_body(adapter, "interactive"))
        # ... and nothing a run spawns carries the seat's state file to write over
        with patch.dict(os.environ, {"IDLE_COMPACT_STATE": "/tmp/seat.json"}):
            self.assertNotIn("IDLE_COMPACT_STATE", config.child_env())


class Listing(unittest.TestCase):
    """`ak orch list --why` answers for every seat whether it compacts itself."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5e-list-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root), "NO_COLOR": "1"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()

    def test_v5e_k_every_seat_is_told_whether_and_how_it_compacts_itself(self):
        seats, kept = [], {}
        for name, model in (("one", "fable"), ("two", "astra"), ("three", "spark")):
            seats.append({"name": name, "path": "/tmp", "created": time.time() - 3600,
                          "attached": False, "exited": False, "legacy": False,
                          "resumable": True, "repo": None})
            kept[name] = {"orchestrator": model, "conversation": "c", "id_source": orch.LAUNCHER}
        (config.STATE / "compact-two.json").write_text(json.dumps(
            {"session": "two", "harness": "codex", "last_compact_at": time.time() - 720,
             "context_tokens": 51000}))
        # left by an earlier seat of this name: it compacted that one, and says nothing of this
        (config.STATE / "compact-three.json").write_text(json.dumps(
            {"session": "three", "harness": "muse", "last_compact_at": time.time() - 90000,
             "context_tokens": 44000}))
        out = subprocess.run([sys.executable, "-c", CHECK_LIST], input=json.dumps(
            {"root": str(self.root), "seats": seats, "records": kept}).encode(),
            capture_output=True, cwd=str(REPO))
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        text = out.stdout.decode()
        self.assertIn("compacts:  yes (claude, hook)", text)
        self.assertIn("compacts:  yes (codex, hook), compacted 12m ago", text)
        self.assertIn("compacts:  yes (muse, screen)", text)
        self.assertNotIn("compacts:  yes (muse, screen), compacted", text)


# `ak orch list --why` in a process of its own, so the seats it reads are only the fake ones.
CHECK_LIST = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from agentkit import config, orch

given = json.load(sys.stdin)
root = Path(given["root"])
for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
    setattr(config, name, root / name.lower())
with patch.object(orch, "listing", return_value=given["seats"]), \
     patch.object(config, "session_records", return_value=given["records"]):
    raise SystemExit(orch.cmd_list(["--why"]))
'''


if __name__ == "__main__":
    unittest.main(verbosity=2)

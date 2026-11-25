"""Every `turn_usage` row written records the machine its turn ran on.

A turn that ran on this host records this host's own name (`socket.gethostname()`), and one that
ran on another machine records its listed name, the same names their kept readings carry
(`agentkit/readings.py`).  A turn a machine turned away (after `prepare`, exiting 252 / FULL),
that then ran here, records this host; a turn that failed or was killed on a machine records that
machine; and rows written before the column existed stay empty (NULL).

Black-box: AK_BIN runs tasks through tests/fixtures/akbin.py on tests/fixtures/akmachine.py, and
history.db is read with sqlite3.
"""

from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OWNERS = {"AK_NOTIFY_SINK": None}
CALM = json.dumps({"cpus": 4, "load": 0, "free_mb": 16000, "mem_total_mb": 32000})
WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'

CLAUDE_EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"type": "system", "subtype": "init", "session_id": "session-acme"},
    {"type": "result", "subtype": "success", "session_id": "session-acme",
     "usage": {"input_tokens": 10, "output_tokens": 20},
     "modelUsage": {"claude-opus-5": {"inputTokens": 10, "outputTokens": 20}}}))
CLAUDE_PARTIAL = "".join(json.dumps(event) + "\n" for event in (
    {"type": "system", "subtype": "init", "session_id": "session-acme"},
    {"type": "assistant", "session_id": "session-acme",
     "message": {"id": "msg-1", "model": "claude-opus-5",
                 "usage": {"input_tokens": 12, "output_tokens": 8}}}))
CODEX_EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"type": "thread.started", "thread_id": "thread-acme"},
    {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 15}}))

OLD_TURN_USAGE = (
    "CREATE TABLE turn_usage (turn TEXT, run_id TEXT, role TEXT, account TEXT, "
    "model TEXT, began REAL, at REAL, input INTEGER, cache_write INTEGER, "
    "cache_read INTEGER, output INTEGER)")


def rows(home, run_id=None):
    with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
        db.row_factory = sqlite3.Row
        if run_id is None:
            return [dict(row) for row in db.execute(
                "SELECT * FROM turn_usage ORDER BY rowid")]
        return [dict(row) for row in db.execute(
            "SELECT * FROM turn_usage WHERE run_id=? ORDER BY began, role", (run_id,))]


class ATurnRecordsItsMachine(unittest.TestCase):
    def stage(self, claude, codex):
        """A Home with `acme-linux` marked for turns and fake harnesses installed on both."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        akconfig.write(home, ["opus", "astra"],
                       extra='[machines.acme-linux]\nwork = ["turns"]\n')
        fakeadapter.install(home, claude=claude, codex=codex)
        machine = akmachine.install(home, cpus=2)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        return home, rig, machine

    def test_remote_and_local_turns_each_name_their_own_machine_and_old_rows_stay_empty(self):
        # Adapters writing a `machine` file (even binary or spoofed) or `machine/` subdir in
        # their own out dir neither interfere with collection nor spoof the recorded machine.
        home, rig, _ = self.stage(
            claude=[{**fakeadapter.WORK,
                     "sh": f'{WHERE}; mkdir -p "${{AK_HAND_IN%/*}}/machine" && '
                           'printf "%s" "${container:-here}" >"${AK_HAND_IN%/*}/machine/artifact"',
                     "events": CLAUDE_EVENTS},
                    {**fakeadapter.WORK,
                     "sh": f'{WHERE}; printf "spoofed-machine" >"${{AK_HAND_IN%/*}}/machine"',
                     "events": CLAUDE_EVENTS}],
            codex=[{**fakeadapter.PASS, "sh": WHERE, "events": CODEX_EVENTS},
                   {**fakeadapter.PASS,
                    "sh": f'{WHERE}; printf "\\377" >"${{AK_HAND_IN%/*}}/machine"',
                    "events": CODEX_EVENTS}])
        # A pre-existing turn_usage table from before the machine column existed.
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute(OLD_TURN_USAGE)
            db.execute("INSERT INTO turn_usage VALUES ('/old/turn', 'old-run', 'executor', "
                       "'default', 'claude-opus-5', 100, 110, 5, 0, 0, 5)")

        # First run: host is crowded -> turns go to acme-linux.
        remote_done = home.ak("run", str(taskfile.write(home, rig.path, name="remote.md")),
                              "--no-merge",
                              env={**OWNERS, "AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertEqual(remote_done.code, 0, remote_done.out + remote_done.err)
        remote_run = taskfile.only_run(home)
        self.assertEqual(sorted(p.read_text().strip() for p in remote_run.rglob("where")),
                         ["docker", "docker"])
        self.assertEqual([p.read_text().strip() for p in remote_run.rglob("machine/artifact")],
                         ["docker"])

        # Second run: host is calm -> turns run on this host.
        local_done = home.ak("run", str(taskfile.write(home, rig.path, name="local.md")),
                             "--no-merge",
                             env={**OWNERS, "AK_HOST_READINGS": CALM}, timeout=300)
        self.assertEqual(local_done.code, 0, local_done.out + local_done.err)
        local_run = next(p for p in (home.path / ".agentkit/runs").iterdir()
                         if p.is_dir() and p != remote_run)
        self.assertEqual(sorted(p.read_text().strip() for p in local_run.rglob("where")),
                         ["here", "here"])

        old = rows(home, "old-run")
        self.assertEqual(len(old), 1)
        self.assertIsNone(old[0]["machine"])

        remote_rows = rows(home, remote_run.name)
        self.assertEqual([(r["role"], r["machine"]) for r in remote_rows],
                         [("executor", "acme-linux"), ("reviewer", "acme-linux")])

        here = socket.gethostname()
        local_rows = rows(home, local_run.name)
        self.assertEqual([(r["role"], r["machine"]) for r in local_rows],
                         [("executor", here), ("reviewer", here)])

    def test_a_turn_turned_away_by_a_machine_records_this_host(self):
        home, rig, machine = self.stage(
            claude={**fakeadapter.WORK, "sh": WHERE, "events": CLAUDE_EVENTS},
            codex={**fakeadapter.PASS, "sh": WHERE, "events": CODEX_EVENTS})
        # Report room during `probe`, then too little memory once `prepare` created a reservation
        # so `turn` exits 252 (helper.FULL) and ak falls back to running here.
        seen = machine / "prepared"
        (machine / "bin/free").write_text(
            "#!/bin/sh\n"
            f'if [ -n "$(find "$HOME/.agentkit-helper" -maxdepth 2 -name reserved 2>/dev/null)" ]; then\n'
            f'  touch "{seen}"\n'
            "  printf '%s\\n' '  total used' 'Mem: 1024 512'\n"
            "else\n"
            "  printf '%s\\n' '  total used' 'Mem: 65536 1024'\n"
            "fi\n")
        (machine / "bin/free").chmod(0o755)
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                       env={**OWNERS, "AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(seen.exists(), "the machine never turned the prepared turn away")
        run_dir = taskfile.only_run(home)
        self.assertEqual(sorted(p.read_text().strip() for p in run_dir.rglob("where")),
                         ["here", "here"])
        here = socket.gethostname()
        self.assertEqual([(r["role"], r["machine"]) for r in rows(home, run_dir.name)],
                         [("executor", here), ("reviewer", here)])

    def test_a_failed_turn_on_a_machine_records_that_machine(self):
        home, rig, _ = self.stage(
            claude={"sh": WHERE, "events": CLAUDE_EVENTS, "final": "## Summary\nfailed",
                    "hand_in": [["blocked", "fixture failure"]], "exit": 1},
            codex={**fakeadapter.PASS, "sh": WHERE, "events": CODEX_EVENTS})
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                       env={**OWNERS, "AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertNotEqual(done.code, 0)
        run_dir = taskfile.only_run(home)
        self.assertEqual([p.read_text().strip() for p in run_dir.rglob("where")], ["docker"])
        kept = rows(home, run_dir.name)
        self.assertEqual([(r["role"], r["machine"]) for r in kept], [("executor", "acme-linux")])

    def test_a_killed_turn_on_a_machine_records_that_machine(self):
        home, rig, _ = self.stage(
            claude={"sh": f"{WHERE}; printf '%s' '{CLAUDE_PARTIAL}' >>\"${{AK_HAND_IN%/*}}/events.jsonl\"; "
                          "while true; do sleep 0.2; done"},
            codex={**fakeadapter.PASS, "sh": WHERE, "events": CODEX_EVENTS})
        proc = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge",
                          env={**OWNERS, "AK_HOST_READINGS": akmachine.CROWDED})
        deadline = time.monotonic() + 120
        run_dir = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail("run ended before the turn streamed: "
                          + home.log("spawn-1.err").read_text())
            runs = [p for p in (home.path / ".agentkit/runs").iterdir() if p.is_dir()] \
                if (home.path / ".agentkit/runs").is_dir() else []
            if runs:
                run_dir = runs[0]
                events = sorted(run_dir.glob("round-1/*/events.jsonl"))
                if events and "msg-1" in events[0].read_text(errors="replace"):
                    break
            time.sleep(0.2)
        else:
            self.fail("the turn on acme-linux never streamed its event")
        stopped = home.ak("run", "stop", run_dir.name, env=OWNERS)
        self.assertEqual(stopped.code, 0, stopped.out + stopped.err)
        proc.wait(timeout=30)
        kept = rows(home, run_dir.name)
        self.assertEqual([(r["role"], r["machine"]) for r in kept], [("executor", "acme-linux")])


if __name__ == "__main__":
    unittest.main()

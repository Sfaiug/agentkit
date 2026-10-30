"""A model or effort changed by hand inside an OpenCode or Muse seat becomes that seat's own, as
`/model` typed in a Claude or Codex seat does (the owner, 30 Oct 2026): once ak has looked at
the seat, `ak orch list` names the model its latest answer since the launch ran on, and its
record holds the effort OpenCode recorded with it.  Muse records no effort of a session's own,
so a Muse seat follows the model alone.  An answer from before the launch moves nothing.
Black-box: `AK_BIN` lists akseat.py seats on each harness's prompt screen, whose answers are
written where each harness keeps them -- opencode.db's rows as OpenCode 2.1.1 writes them, a
session.jsonl's lines as Muse 1.4 does; it fails against `/bin/false`."""

import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

FLASH, GLM = "deepseek-v4.1-flash-free", "glm-5.3-flash-free"
SPARK, WONDER = "muse-spark-1.3-contributor", "muse-wonder-full-1.0"
MESSAGES = """CREATE TABLE `session_message` (
          `id` text PRIMARY KEY,
          `session_id` text NOT NULL,
          `type` text NOT NULL,
          `seq` integer NOT NULL,
          `time_created` integer NOT NULL,
          `time_updated` integer NOT NULL,
          `data` text NOT NULL
        )"""


def answered(db, session, seq, at, model, variant):
    """An OpenCode answer of `model` at that variant, `at` seconds since the epoch."""
    ms = int(at * 1000)
    data = {"time": {"created": ms, "completed": ms + 400}, "agent": "build",
            "model": {"id": model, "providerID": "opencode", "variant": variant},
            "content": [{"type": "text", "text": "Renamed the acme report."}], "finish": "stop"}
    db.execute("INSERT INTO session_message VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
               (f"msg_0fa1c2d3e4ff{seq:010d}", session, seq, ms, ms + 400, json.dumps(data)))


def muse_line(session, at, payload_type, payload):
    return json.dumps({"schema_version": 1, "id": f"01a18c52-0000-7000-8000-{int(at):012d}",
                       "stream": {"kind": "session", "id": session},
                       "recorded_at": int(at * 1_000_000), "record_type": "event",
                       "durability": "durable", "payload_type": payload_type,
                       "payload_schema_version": 1, "payload": payload})


def muse_answer(session, run, at, model, source):
    """A Muse run on `model`, configured `source`, and its one model request, `at` seconds."""
    configured = {"kind": "run_model", "record": {
        "command_id": run, "display_label": model, "model_id": model, "provider_id": "meta",
        "run_stream": {"id": run, "kind": "run"}, "source": source}}
    completed = {"event": {"duration_ms": 9000, "finish_reason": None, "kind": "model_completed",
                           "model": model, "usage": {"input_tokens": 4100, "output_tokens": 90}},
                 "kind": "run", "run_id": run}
    return (muse_line(session, at - 10, "run.model.configured", configured) + "\n"
            + muse_line(session, at, "runtime.session", completed) + "\n")


def orchestrators(home):
    """Each seat's orchestrator as `ak orch list` names it, once it has exited 0."""
    done = home.ak("orch", "list", env={"COLUMNS": "200"})
    assert done.code == 0, done.err
    header, *rows = done.out.splitlines()
    at = header.index("orchestrator")
    return {row.split()[0]: re.match(r"\S*", row[at:]).group()
            for row in rows if row[:1].strip() and row[at - 1:at] == " "}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelFollowedInsideOpencodeAndMuse(unittest.TestCase):
    def test_an_answer_since_the_launch_moves_the_seat_and_one_before_it_moves_nothing(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "flash": {"harness": "opencode", "model": f"opencode/{FLASH}", "effort": "high"},
            "glm": {"harness": "opencode", "model": f"opencode/{GLM}", "effort": "high"},
            "spark": {}, "wonder": {"harness": "muse", "model": WONDER, "effort": "xhigh"}})
        now = time.time()
        opencode = home.path / ".local/share/opencode/opencode.db"
        opencode.parent.mkdir(parents=True)
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y/%m/%d")
        seats = {}
        for n, (name, harness, launched, moved) in enumerate([
                ("acme-code", "opencode", now - 600, now - 60),
                ("acme-old", "opencode", now - 60, now - 600),
                ("acme-muse", "muse", now - 600, now - 60),
                ("acme-muse-old", "muse", now - 60, now - 600)]):
            token = f"{n:x}" * 32
            receipt = f".agentkit/state/{harness}-launch-{token}/session"
            if harness == "opencode":
                session = f"ses_0fa1c2d3e4ffAcmeModel{n}"
                with closing(sqlite3.connect(opencode)) as db, db:
                    if not n:
                        db.execute(MESSAGES)
                    answered(db, session, 10 * n + 1, now - 900, FLASH, "high")
                    db.execute("INSERT INTO session_message VALUES (?, ?, 'model-switched', ?,"
                               " ?, ?, ?)", (f"msg_0fa1c2d3e4ffSwitch{n}", session, 10 * n + 2,
                                             int(moved * 1000) - 5000, int(moved * 1000) - 5000,
                                             json.dumps({"model": {"id": GLM, "variant": "max",
                                                                   "providerID": "opencode"}})))
                    answered(db, session, 10 * n + 3, moved, GLM, "max")
                seats[name] = Seat(home, name, model="flash", screen="opencode-prompt-pane.txt",
                                   record={"launched": launched, "opencode_launch": token})
            else:
                session = f"01a18c52-a770-75a1-9576-acme0000000{n}"
                home.write(f".local/share/muse/sessions/{day}/{session}/session.jsonl",
                           muse_answer(session, "01a18c52-0000-7000-8000-run000000001",
                                       now - 900, SPARK, "startup")
                           + muse_answer(session, "01a18c52-0000-7000-8000-run000000002",
                                         moved, WONDER, "model_reconfigure"))
                seats[name] = Seat(home, name, model="spark", screen="muse-prompt-pane.txt",
                                   record={"launched": launched, "muse_launch": token})
            home.write(receipt, session)
        # the list reads each seat's record before it looks at the seat: a look's move shows
        # from the next listing on
        orchestrators(home)
        self.assertEqual(orchestrators(home), {"acme-code": "glm", "acme-old": "flash",
                                               "acme-muse": "wonder", "acme-muse-old": "spark"})

        def effort(name, model):
            record = json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())
            return ((record.get("efforts") or {}).get(model) or {}).get("effort")
        self.assertEqual(effort("acme-code", "glm"), "max")
        self.assertIsNone(effort("acme-old", "glm"))


if __name__ == "__main__":
    unittest.main()

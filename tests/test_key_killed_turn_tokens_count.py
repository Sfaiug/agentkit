"""An ending counts the completed model calls of the turn it killed, once.

Black-box: AK_BIN, fakeadapter's usage files, and a throwaway HOME's history.db.  Finished
turns keep their existing totals; the tick can publish a lost ending without adding them again.
"""

import json
import shlex
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.gitrig import Rig

OWNERS = {"AK_NOTIFY_SINK": None}
# Two completed calls, followed by an event cut off before its usage arrived.
PARTIAL = "".join(json.dumps({"type": "message", "message": {
    "id": str(n), "usage": {"input_tokens": incoming, "output_tokens": outgoing}}}) + "\n"
                  for n, incoming, outgoing in ((1, 100, 20), (2, 200, 30))) + '{"type":'
REVIEW = json.dumps({"type": "turn.completed", "usage": {
    "input_tokens": 50, "output_tokens": 10}}) + "\n"


class KilledTurnTokensCount(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        akconfig.write(self.home, ["opus", "astra"])
        self.steps = {"claude": {**fakeadapter.WORK, "events": PARTIAL},
                      "codex": {**fakeadapter.PASS, "events": REVIEW}}
        self.fakes = fakeadapter.install(self.home, **self.steps)
        self.db = self.home.path / ".agentkit/history.db"
        self.task = taskfile.write(self.home, self.rig.path)

    def row(self):
        with sqlite3.connect(self.db) as db:
            return db.execute("SELECT final_state, executor_tokens, reviewer_tokens "
                              "FROM runs WHERE run_id=?", (self.run_dir.name,)).fetchone()

    def stop(self, harness, *before):
        folder = self.fakes[harness].dir
        held, release = folder / "held", folder / "release"
        self.addCleanup(release.touch)
        self.fakes[harness].behave(*before, {**self.steps[harness], "sh": (
            f"touch {shlex.quote(str(held))}; "
            f"while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done")})
        proc = self.home.spawn("run", str(self.task), "--no-merge", env=OWNERS)
        deadline = time.monotonic() + 120
        while not held.exists():
            self.assertIsNone(proc.poll(), self.home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, "the turn never wrote its usage")
            time.sleep(0.1)
        self.run_dir = taskfile.only_run(self.home)
        done = self.home.ak("run", "stop", self.run_dir.name, env=OWNERS)
        self.assertEqual(done.code, 0, done.out + done.err)
        proc.wait(timeout=30)
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["state"], "stopped")

    def test_a_stop_counts_the_executor_calls_that_finished_before_the_kill(self):
        self.stop("claude")
        self.assertEqual(self.row(), ("stopped", 350, None))

    def test_a_stop_counts_the_reviewer_without_recounting_the_finished_executor(self):
        self.stop("codex")
        self.assertEqual(self.row(), ("stopped", 350, 60))

    def test_a_killed_turn_uses_its_harness_to_count_only_its_share_of_a_resumed_thread(self):
        akconfig.write(self.home, ["astra", "opus"])
        first = {**fakeadapter.WORK, "events": json.dumps({
            "type": "thread.started", "thread_id": "thread-acme"}) + "\n" + REVIEW}
        self.steps["codex"] = {**first, "events": first["events"].replace(
            '"input_tokens": 50', '"input_tokens": 90')}
        self.fakes["claude"].behave("fail")
        self.stop("codex", first)
        self.assertEqual(self.row(), ("stopped", 100, None))

    def test_finished_turns_keep_the_totals_recorded_before_this_change(self):
        done = self.home.ak("run", str(self.task), "--no-merge", env=OWNERS, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.run_dir = taskfile.only_run(self.home)
        self.assertEqual(self.row(), ("pass", 350, 60))

    def test_a_harness_reporting_nothing_leaves_tokens_unknown(self):
        self.fakes["claude"].behave(fakeadapter.WORK)
        self.fakes["codex"].behave(fakeadapter.PASS)
        done = self.home.ak("run", str(self.task), "--no-merge", env=OWNERS, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.run_dir = taskfile.only_run(self.home)
        self.assertEqual(self.row(), ("pass", None, None))

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_the_tick_republishing_an_ending_adds_no_tokens(self):
        self.stop("codex")
        # Even a later reading that disagrees cannot rewrite a turn already counted.
        for events in self.run_dir.glob("round-*/*/events.jsonl"):
            events.write_text(json.dumps({"type": "result", "usage": {"tokens": 999}}) + "\n")
        for _ in range(2):
            with sqlite3.connect(self.db) as db:
                db.execute("UPDATE runs SET final_state='running', finished_at=NULL")
            done = self.home.tick(env=OWNERS)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(self.row(), ("stopped", 350, 60))


if __name__ == "__main__":
    unittest.main()

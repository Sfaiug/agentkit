"""An OpenCode seat's Stop names the background work it still has in flight, as a Claude seat's
does.

OpenCode 2.1.1 keeps a `job.background/<notification>` row in opencode.db's kv table for each
background shell and subagent, `running` until it ends, and wakes the session at that end.  The
seat plugin (hooks/opencode-seat) hands its Stop the stopping session's in Claude's shape: a
Stop with a shell and a subagent running records `holds` naming both and the seat reads
working; the subagent's own end after it changes nothing; one with nothing running reads idle
and holds nothing; a shell and a subagent a killed process left `running` there are no work
held, as on a live OpenCode 2.1.1 seat ended under both on 27 Oct 2026, whose restarted process
found their rows as they were, written before it began; and a seat whose Stop held a shell alone
stays on an account with usage left, where a bare Stop moves it.
Black-box: the plugin runs under Node as OpenCode loads it, handed one
`session.execution.succeeded`; the fake OpenCode is its database, each table's schema and each
row's shape copied from OpenCode 2.1.1 as installed (the kv table its KV service creates and
the record Job.background writes, `Ll` in its bundle; session_v2, of it the columns a session
is created with), read through a
`node:sqlite` of Python's sqlite3 where Node has none of its own, as Bun 1.4.2 has.  `ak` runs
from outside through tests/fixtures/akbin.py beside a seat of tests/fixtures/akseat.py, on fake
harnesses of fakeadapter.py and the usage readings the test writes.
"""

import json
import os
import shlex
import shutil
import socket
import sqlite3
import sys
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home, boxable
from fixtures.akseat import PANE, Seat

NODE = shutil.which("node")
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TWO = {"accounts": ["default", "second"]}
TOKEN, SID, CHILD = "b" * 32, "ses_0fa1c2d3e4ffAcmeStop01", "ses_0fa1c2d3e4ffAcmeChild1"
KV = """CREATE TABLE `kv` (
          `key` text PRIMARY KEY,
          `value` text NOT NULL,
          `time_created` integer NOT NULL,
          `time_updated` integer NOT NULL
        )"""
SESSIONS = """CREATE TABLE `session_v2` (
          `id` text PRIMARY KEY,
          `project_id` text NOT NULL,
          `parent_id` text,
          `slug` text NOT NULL,
          `directory` text NOT NULL,
          `version` text NOT NULL,
          `time_created` integer NOT NULL,
          `time_updated` integer NOT NULL
        )"""
SHELL = {"id": "sh_0fa1c2d3e4ffAcmeBuild", "notificationID": "msg_0fa1c2d3e4ffAcmeShell",
         "recovery": {"kind": "shell", "sessionID": SID, "shellID": "sh_0fa1c2d3e4ffAcmeBuild",
                      "command": "make acme"}, "status": "running"}
SUBAGENT = {"id": CHILD, "notificationID": "msg_0fa1c2d3e4ffAcmeAgent",
            "recovery": {"kind": "subagent", "parentSessionID": SID,
                         "childSessionID": CHILD, "agent": "general",
                         "description": "Check the acme parser"}, "status": "running"}
# a shell another session started, and one of this session's that ended but is not yet handed back
OTHERS = [{**SHELL, "notificationID": "msg_0fa1c2d3e4ffOtherShell",
           "recovery": {**SHELL["recovery"], "sessionID": "ses_0fa1c2d3e4ffOther"}},
          {**SHELL, "notificationID": "msg_0fa1c2d3e4ffEndedShell", "status": "completed",
           "output": "done"}]
# the same work as the process before this one left it: still `running`
LOST = [{**SHELL, "notificationID": "msg_0fa1c2d3e4ffAcmeLostShell"},
        {**SUBAGENT, "notificationID": "msg_0fa1c2d3e4ffAcmeLostAgent"}]
# node:sqlite as Bun offers it, reading through Python's sqlite3, for a Node without its own
SQLITE = r"""
import { spawnSync } from "node:child_process";
const READ = `import json, sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
print(json.dumps([dict(row) for row in db.execute(sys.argv[2], json.loads(sys.argv[3]))]))`;
export class DatabaseSync {
  constructor(file, options) {
    if (!options?.readOnly) throw new Error("the plugin only reads");
    this.file = file;
  }
  prepare(sql) {
    const all = (...params) => {
      const run = spawnSync(process.env.FAKE_PYTHON,
        ["-c", READ, this.file, sql, JSON.stringify(params)], { encoding: "utf8" });
      if (run.status !== 0) throw new Error(run.stderr);
      return JSON.parse(run.stdout);
    };
    return { all, get: (...params) => all(...params)[0] };
  }
  close() {}
}
"""
DRIVER = r"""
import { register } from "node:module";
import { pathToFileURL } from "node:url";
const [plugin, sqlite, sid] = process.argv.slice(1);
if (!await import("node:sqlite").then(() => true, () => false)) {
  const url = JSON.stringify(pathToFileURL(sqlite).href);
  register("data:text/javascript," + encodeURIComponent(`export async function resolve(name,
    c, next) { return name === "node:sqlite" ? { url: ${url}, shortCircuit: true }
      : next(name, c); }`));
}
const seat = (await import(pathToFileURL(plugin).href)).default;
let done;
const drained = new Promise((resolve) => { done = resolve; });
const events = [{ type: "session.execution.succeeded", data: { sessionID: sid } }];
const ctx = { session: { get: async () => ({}) },
  event: { subscribe: async function* () { yield* events; done(); } } };
const stop = await seat.setup(ctx);
await drained;
stop();
"""


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeStopHoldsBackgroundWork(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["mimo"], providers={"mimo": TWO})
        self.fake = fakeadapter.install(home, opencode="pass")["opencode"]
        home.write(f".agentkit/state/opencode-launch-{TOKEN}/session", SID)
        self.seat = Seat(home, "acme", model="mimo", screen="opencode-prompt-pane.txt",
                         record={"opencode_launch": TOKEN, "account": "default"})
        self.fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(self.seat.screen_file), str(self.seat.typed_file)]))

    def stop(self, *jobs, ended=SID, lost=()):
        """A turn of SID or its subagent CHILD ends with those jobs in opencode.db, written while
        the plugin's process runs, and the `lost` ones written an hour before it began: the fact
        the seat holds after."""
        db = self.home.path / ".local/share/opencode/opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        db.unlink(missing_ok=True)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(KV)
            conn.execute(SESSIONS)
            conn.executemany(
                "INSERT INTO session_v2 VALUES (?, 'prj_acme', ?, ?, ?, '2.1.1', 0, 0)",
                [(SID, None, "acme", "/acme"), (CHILD, SID, "acme-check", "/acme")])
            now = int(time.time() * 1000)
            conn.executemany("INSERT INTO kv VALUES (?, ?, ?, ?)", [
                (f"job.background/{job['notificationID']}", json.dumps(job), at, at)
                for at, part in ((now + 60_000, jobs), (now - 3_600_000, lost)) for job in part])
        fake = self.home.root / "sqlite.mjs"
        fake.write_text(SQLITE)
        done = self.home.run(NODE, "--input-type=module", "-e", DRIVER,
                             str(REPO / "hooks/opencode-seat/index.js"), str(fake), ended,
                             env={"AGENTKIT_SESSION": "acme", "FAKE_PYTHON": sys.executable})
        self.assertEqual(done.code, 0, done.err)
        return json.loads((self.home.path / ".agentkit/state/hook-acme.json").read_text())

    def word(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()[0]

    def tick(self, used):
        """One tick with the first account `used`% into its 5h window and the other at 10%, the
        seat's terminal untouched for ten minutes: the account it is on after."""
        now = time.time()

        def reading(used):
            return {"provider": "mimo", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"mimo": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        tty = self.home.tmux("display-message", "-p", "-t", self.seat.pane, "#{pane_tty}")
        os.utime(tty.out.strip(), (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads((self.home.path / ".agentkit/state/session-acme.json")
                          .read_text()).get("account")

    def test_a_shell_and_a_subagent_running_are_held_and_the_seat_works(self):
        fact = self.stop(SHELL, SUBAGENT, *OTHERS)
        self.assertEqual((fact["event"], fact["kind"], fact["holds"]),
                         ("Stop", "background", ["shell", "subagent"]))
        self.assertEqual(self.word(), "acme  working")

    def test_a_subagent_s_own_end_is_no_end_of_the_seat_s_turn(self):
        self.stop(SHELL, SUBAGENT)
        fact = self.stop(SHELL, ended=CHILD)
        self.assertEqual((fact["kind"], fact["holds"]), ("background", ["shell", "subagent"]))
        self.assertEqual(self.word(), "acme  working")

    def test_work_a_killed_process_left_running_is_not_held(self):
        fact = self.stop(*OTHERS, lost=LOST)
        self.assertEqual((fact["event"], fact["kind"]), ("Stop", ""))
        self.assertNotIn("holds", fact)
        self.assertEqual(self.word(), "acme  idle")
        fact = self.stop(SHELL, lost=LOST)
        self.assertEqual((fact["kind"], fact["holds"]), ("", ["shell"]))

    def test_nothing_running_is_a_turn_over_holding_nothing(self):
        fact = self.stop(*OTHERS)
        self.assertEqual((fact["event"], fact["kind"]), ("Stop", ""))
        self.assertNotIn("holds", fact)
        self.assertEqual(self.word(), "acme  idle")

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_held_shell_keeps_the_seat_on_an_account_with_usage_left(self):
        fact = self.stop(SHELL)
        self.assertEqual((fact["kind"], fact["holds"]), ("", ["shell"]))
        self.assertEqual(self.tick(97), "default")
        self.stop()
        self.assertEqual(self.tick(97), "second")


if __name__ == "__main__":
    unittest.main()

"""An OpenCode seat follows the session its own OpenCode last took a prompt into, and keeps each
one it left for its done check.  In session A the owner asks for a retry button and a receipt
email; the plan holds the button alone, every line done.  They prompt B, saying only "thanks".
The seat does not read done, `ak orch check` names the email from a workspace holding A and B,
and a reopen resumes B.  A prompt in A again leaves the check reading each once; a prompt into a
subagent's session, or into one another seat's record names, leaves the seat where it was, its
first session too, or in none though that seat is forgotten.  A seat reopened on A, its receipt
naming A and its record none, that goes to B before any prompt in A keeps A just the same, and
stays on A through a prompt into beta's; one whose receipt an earlier plugin wrote naming
beta's or one beta left reopens on none; a seat whose OpenCode's session API never answers
follows all the same; a prompt in a further server, one a tool's shell or the seat's own server
started, moves nothing.  A prompt's hook whose write into the receipt stalls until a later
prompt's hook has ended leaves the receipt naming the later prompt's session.
Black-box on `AK_BIN`, a fake model (fakeadapter.py), and in the seat's pane a fake `opencode`,
two processes as 2.2.7's: its TUI and, a child of that, the `opencode serve --stdio` that runs
the plugin under Node as OpenCode loads it and hands it a `session.inbox.enqueued` for each
prompt, its record of every session an opencode.db -- each session's row in session_v2, a
subagent's naming its parent, and each prompt and its answer in session_message, shaped as
tests/test_key_card_answers_opencode.py's.  One process as 2.2.6's, the plugin in its TUI,
follows and is left where it was the same.
"""

import json
import os
import shlex
import shutil
import sqlite3
import sys
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, REPO, Home
from fixtures.akseat import PANE, Seat

NODE = shutil.which("node")
TOKEN = "c" * 32
A, B = "ses_0fa1c2d3e4ffAcmeUpload", "ses_0fa1c2d3e4ffAcmeThanks"
SUB = "ses_0fa1c2d3e4ffAcmeParser"                                     # A's subagent
OWN, LEFT = "ses_0fa1c2d3e4ffBetaOwn", "ses_0fa1c2d3e4ffBetaLeft"        # beta's
EMAIL = "email me a receipt after every upload"
FIRST = f"Add a retry button to the upload page, and {EMAIL}."
# The TUI: each prompt the test enters (`said`) is written into opencode.db, the owner's words and
# an answer, and handed to the plugin; once the plugin has reported it, it goes to `heard`.  Its
# session API answers from opencode.db, or never (`api`), which says how it runs too: as 2.2.6's
# one process where that is the `--prompt` a seat's first message is launched as, and with a
# further server taking the prompts where it ends `nested`, one a tool's shell started, or
# `spawned`, one the server itself started.
OPENCODE = r'''const { spawn, spawnSync } = require("node:child_process");
const { appendFileSync, readFileSync } = require("node:fs");
const { pathToFileURL } = require("node:url");
const SERVE = ["serve", "--stdio", "--port", "0"];     // how 2.2.7's TUI starts its server
const serve = process.argv[2] === SERVE[0], own = process.argv.slice(serve ? 6 : 2);
const [plugin, python, db, said, heard, api, ...pane] = own;
const SQL = `import json, sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    db.row_factory = sqlite3.Row
    print(json.dumps([dict(row) for row in db.execute(sys.argv[2], json.loads(sys.argv[3]))]))`;
const sql = (query, ...params) => JSON.parse(spawnSync(python,
  ["-c", SQL, db, query, JSON.stringify(params)], { encoding: "utf8" }).stdout);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let seq = 0;

async function* prompts() {
  for (let seen = 0; ; await sleep(50)) {
    let lines = [];
    try { lines = readFileSync(said, "utf8").split("\n").filter(Boolean).slice(seen); } catch {}
    for (const line of lines) {
      seen++;
      const [sessionID, text] = JSON.parse(line);
      for (const [type, data] of [["user", { text }],
                                  ["assistant", { content: [{ type: "text", text: "Done." }] }]]) {
        seq++;
        sql("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)", `msg_0fa1c2d3e4ff${seq}`,
            sessionID, type, seq, Date.now(), Date.now(), JSON.stringify(data));
      }
      yield { type: "session.inbox.enqueued",
              data: { sessionID, item: { type: "user", payload: { text } } } };
      await sleep(0);     // the plugin's hook, run synchronously, has ended by now
      appendFileSync(heard, line + "\n");
    }
  }
}

const ctx = {
  session: { get: async ({ sessionID }) => {
    if (api === "hangs") return new Promise(() => {});
    const [row] = sql("SELECT id, parent_id FROM session_v2 WHERE id = ?", sessionID);
    return row && { id: row.id, parentID: row.parent_id };
  } },
  event: { subscribe: prompts },
};
console.log = () => {};     // OpenCode keeps a plugin's log off its screen
const FURTHER = { nested: ["/bin/sh", "-c", '"$@" & wait', "sh"], spawned: [] };  // its starter
function takePrompts() {
  const by = !process.env.NESTED && FURTHER[api.split(" ").pop()];
  if (by) {
    const [program, ...args] = [...by, process.execPath, __filename, ...SERVE, ...own];
    spawn(program, args, { stdio: "inherit", env: { ...process.env, NESTED: "1" } });
  } else import(pathToFileURL(plugin).href).then((loaded) => loaded.default.setup(ctx));
}
if (serve) {
  const tui = process.ppid;
  setInterval(() => process.ppid === tui || process.exit(), 100);     // it ends with its TUI
  takePrompts();
} else {
  spawn(python, pane, { stdio: "inherit" });
  if (api.startsWith("--prompt=")) takePrompts();
  else spawn(process.execPath, [__filename, ...SERVE, ...own], { stdio: "inherit" });
}
'''


def arguments(receipt, held=()):
    """The arguments of each process running under the launch whose receipt that is, but those
    whose pid is `held`."""
    launch = f"AGENTKIT_OPENCODE_RECEIPT={receipt}".encode()
    for proc in Path("/proc").glob("[0-9]*"):
        if int(proc.name) in held:
            continue
        try:
            if launch in (proc / "environ").read_bytes().split(b"\0"):
                yield (proc / "cmdline").read_bytes().split(b"\0")[:-1]
        except OSError:
            pass        # gone meanwhile


class Rig:
    """The seat acme, its OpenCode in its pane and taking no prompt yet, beside beta."""
    API = "answers"

    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, opencode="pass", claude="pass")
        self.fake, self.opencode = fakes["claude"], fakes["opencode"]
        self.opencode.answer("interactive", "", 3, given=["new"])   # OpenCode takes no id of ours
        akconfig.write(home, ["mimo", "opus"], extra='[done_check]\nmodel = "opus"')
        # a launch whose OpenCode has taken no prompt yet: its receipt names no session
        receipt = home.path / f".agentkit/state/opencode-launch-{TOKEN}"
        receipt.mkdir(parents=True)
        self.seat = seat = Seat(home, "acme", model="mimo", screen="opencode-prompt-pane.txt",
                                composer="┃  Ask anything…",
                                record={"opencode_launch": TOKEN, "conversation": None,
                                        "id_source": None, "resumable": None})
        # in the seat's directory too, so only its record keeps acme off its sessions
        Seat(home, "beta", model="mimo", cwd=seat.cwd, alive=False, record={
            "conversation": OWN, "left": [{"harness": "opencode", "conversation": LEFT}]})
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · "
                   "check: `true` · acme · written 2026-11-07 10:05 · done 0123456789ab\n")
        self.receipt, self.db = receipt, home.path / ".local/share/opencode/opencode.db"
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE `session_v2` (`id` text PRIMARY KEY, `project_id` text"
                         " NOT NULL, `parent_id` text, `slug` text NOT NULL, `directory` text"
                         " NOT NULL, `version` text NOT NULL, `time_created` integer NOT NULL,"
                         " `time_updated` integer NOT NULL)")
            conn.executemany(
                "INSERT INTO session_v2 VALUES (?, 'prj_acme', ?, ?, ?, '2.2.6', 0, 0)",
                [(sid, parent, sid[-6:].lower(), str(seat.cwd)) for sid, parent in
                 ((A, None), (B, None), (SUB, A), (OWN, None), (LEFT, None))])
            conn.execute("CREATE TABLE `session_message` (`id` text PRIMARY KEY, `session_id`"
                         " text NOT NULL, `type` text NOT NULL, `seq` integer NOT NULL,"
                         " `time_created` integer NOT NULL, `time_updated` integer NOT NULL,"
                         " `data` text NOT NULL)")
        self.checked = self.fake.dir / "checked.md"
        self.gap = {"sh": f"cp conversation.md {shlex.quote(str(self.checked))}; "
                          f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                          f"{shlex.quote(EMAIL)} . | head -n 1):1\" 'no receipt email' "
                          f"'the owner asked for it' --quote {shlex.quote(EMAIL)}",
                    "final": "Checked.", "hand_in": [["done"]]}
        opencode = home.root / "opencode"
        opencode.write_text(OPENCODE)
        self.said, self.heard = home.root / "said", home.root / "heard"
        # its first frame is told by the title, which only the screen it draws sets again
        self.assertEqual(home.tmux("select-pane", "-t", seat.pane, "-T", "").code, 0)
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "-c", str(seat.cwd),
                         "-e", "AGENTKIT_SESSION=acme",
                         "-e", f"AGENTKIT_OPENCODE_RECEIPT={receipt}",
                         NODE, str(opencode), str(REPO / "hooks/opencode-seat/index.js"),
                         sys.executable, str(self.db), str(self.said), str(self.heard), self.API,
                         str(PANE),
                         str(seat.screen_file), str(seat.typed_file), seat.composer)
        self.assertEqual(done.code, 0, done.err)
        seat.show("opencode-prompt-pane.txt")

    def say(self, session, text):
        """The owner sends `text` into `session` in the seat's OpenCode, and it is reported."""
        before = self.heard.read_text().count("\n") if self.heard.exists() else 0
        with self.said.open("a") as out:
            out.write(json.dumps([session, text]) + "\n")
        until = time.monotonic() + 120
        while not self.heard.exists() or self.heard.read_text().count("\n") <= before:
            self.assertLess(time.monotonic(), until, "the seat's OpenCode never reported it")
            time.sleep(0.05)

    def prompt(self, session, text, held=()):
        """`say`, and ak has followed it: on a loaded host the hook goes on past the plugin's
        wait for it, its follow the one process of the seat's launch naming the hook
        (hooks/seat-state.sh), but one whose pid is `held`, which the test stalls."""
        self.say(session, text)
        until = time.monotonic() + 120
        hook = str(REPO / "hooks/seat-state.sh").encode()
        while any(hook in argv for argv in arguments(self.receipt, held)):
            self.assertLess(time.monotonic(), until, "ak never ended following it")
            time.sleep(0.05)

    def resumed(self):
        """The session a reopened seat comes back on."""
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        done = self.home.ak("orch", "acme", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        # `interactive <model> <effort> [session-id]`: the session to reopen
        return self.opencode.calls("interactive")[-1]["argv"][2:]

    def assert_found_reading_each_once(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        self.fake.behave(self.gap)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(EMAIL, done.out)
        read = self.checked.read_text()
        self.assertEqual((read.count(EMAIL), read.count(" thanks\n")), (1, 1), read)


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeNewSessionKept(Rig, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.prompt(A, FIRST)
        self.prompt(B, "thanks")

    def test_the_owner_s_words_in_the_session_left_owe_a_check_that_finds_the_gap(self):
        self.assert_found_reading_each_once()

    def test_reopening_the_seat_resumes_the_session_it_went_to(self):
        self.assertEqual(self.resumed(), [B])

    def test_a_prompt_back_in_the_session_left_reads_each_once(self):
        self.prompt(A, "Go on.")
        self.assert_found_reading_each_once()
        self.assertEqual(self.resumed(), [A])

    def test_a_prompt_in_a_subagent_s_session_leaves_the_seat_where_it_was(self):
        self.prompt(SUB, "Check the parser.")
        self.assertEqual(self.resumed(), [B])

    def test_a_prompt_in_another_seat_s_session_leaves_the_seat_where_it_was(self):
        for session in (OWN, LEFT):
            self.prompt(session, "hello")
        self.assertEqual(self.resumed(), [B])


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeFirstSessionKept(Rig, unittest.TestCase):
    def test_a_prompt_in_another_seat_s_session_leaves_the_seat_on_its_first(self):
        self.prompt(A, FIRST)
        for session in (OWN, LEFT):
            self.prompt(session, "hello")
        self.assertEqual(self.resumed(), [A])

    def test_a_first_prompt_in_another_seat_s_session_leaves_the_seat_on_none(self):
        self.assert_on_none_once_its_owner_is_gone(OWN)

    def test_a_first_prompt_in_a_session_another_seat_left_leaves_the_seat_on_none(self):
        self.assert_on_none_once_its_owner_is_gone(LEFT)

    def assert_on_none_once_its_owner_is_gone(self, session):
        self.prompt(session, "hello")
        for _ in range(2):      # beta stopped, then forgotten
            done = self.home.ak("orch", "stop", "beta")
            self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.resumed(), [])


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeEarlierPluginsReceipt(Rig, unittest.TestCase):
    """The plugin before wrote into the receipt each session a prompt went into, refused too."""

    def test_a_receipt_naming_another_seat_s_session_reopens_on_none(self):
        (self.receipt / "session").write_text(OWN)
        self.assertEqual(self.resumed(), [])

    def test_a_receipt_naming_a_session_another_seat_left_reopens_on_none(self):
        (self.receipt / "session").write_text(LEFT)
        self.assertEqual(self.resumed(), [])


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeSessionApiHung(Rig, unittest.TestCase):
    API = "hangs"

    def test_a_session_api_that_never_answers_costs_the_seat_no_session(self):
        self.prompt(A, FIRST)
        self.prompt(B, "thanks")
        self.assert_found_reading_each_once()
        self.assertEqual(self.resumed(), [B])


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeToolsServer(Rig, unittest.TestCase):
    API = "nested"      # each prompt is taken by a server a tool of the seat's OpenCode started

    def test_a_prompt_in_a_further_server_leaves_the_seat_where_it_was(self):
        (self.receipt / "session").write_text(A)       # the launch opened on A
        self.prompt(B, "hello")
        self.assertEqual(self.resumed(), [A])


class OpencodeServersServer(OpencodeToolsServer):
    API = "spawned"     # each prompt is taken by a server the seat's own server started


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeOneProcess(Rig, unittest.TestCase):
    API = "--prompt=Explain opencode serve --stdio"     # ps reads a server's command in it

    def test_reopening_the_seat_resumes_the_session_it_went_to(self):
        self.prompt(A, FIRST)
        self.prompt(B, "thanks")
        self.assertEqual(self.resumed(), [B])


class OpencodeOneProcessToolsServer(OpencodeToolsServer):
    API = OpencodeOneProcess.API + " nested"


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeReopenedSessionKept(Rig, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.receipt / "session").write_text(A)       # the launch opened on A
        at = int(time.time() * 1000) - 60_000
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executemany("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (f"msg_0fa1c2d3e4ffAcme{seq}", A, kind, seq, at + seq, at + seq, json.dumps(data))
                for seq, (kind, data) in enumerate((("user", {"text": FIRST}), ("assistant", {
                    "content": [{"type": "text", "text": "Done."}]})), 1)])

    def test_a_seat_reopened_on_a_session_keeps_it_when_its_first_prompt_goes_elsewhere(self):
        self.prompt(B, "thanks")
        self.assert_found_reading_each_once()

    def test_a_prompt_in_another_seat_s_session_leaves_it_on_the_one_it_reopened_on(self):
        for session in (OWN, LEFT):
            self.prompt(session, "hello")
        self.assertEqual(self.resumed(), [A])


def holders(path):
    """The pid of each process but this one holding `path` open."""
    want = os.stat(path)
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            fds = [] if int(proc.name) == os.getpid() else os.listdir(proc / "fd")
        except OSError:
            continue        # another user's, or gone meanwhile
        for fd in fds:
            try:
                if os.path.samestat(os.stat(proc / "fd" / fd), want):
                    yield int(proc.name)
            except OSError:
                pass        # closed meanwhile


def ended(pid):
    """Whether process `pid` is gone, a zombie its new parent has not reaped yet too."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True
    return state in ("Z", "X")


@unittest.skipUnless(NODE and REAL_TMUX, "no node or no tmux installed")
class OpencodeLateReceiptWrite(Rig, unittest.TestCase):
    """The receipt's `session.next` is a FIFO the test keeps full: the hook of the prompt into A
    stalls writing it, the FIFO is set aside while the prompt into B is followed, and drained
    once that hook has ended, so A's write lands last: back as `session.next`, which A's hook
    then renames over the receipt, or as the receipt itself, as where both hooks opened the one
    `session.next` and B's renamed it."""

    def test_a_late_rename_leaves_the_later_prompt_s_session(self):
        self.assert_late_write_landing_as("session.next")

    def test_a_late_write_into_the_receipt_leaves_the_later_prompt_s_session(self):
        self.assert_late_write_landing_as("session")

    def assert_late_write_landing_as(self, name):
        fifo, aside = self.receipt / "session.next", self.home.root / "held"
        os.mkfifo(fifo)
        pipe = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, pipe)
        full = 0
        for chunk in (4096, 1):
            try:
                while True:
                    full += os.write(pipe, b"x" * chunk)
            except BlockingIOError:
                pass        # no room left for a write of the hook's
        self.say(A, FIRST)
        until = time.monotonic() + 120
        while not (older := next(holders(fifo), None)):
            self.assertLess(time.monotonic(), until, "the hook never began writing the receipt")
            time.sleep(0.05)
        os.rename(fifo, aside)
        self.prompt(B, "thanks", held={older})
        os.rename(aside, self.receipt / name)
        while full:
            full -= len(os.read(pipe, full))
        while not ended(older):
            self.assertLess(time.monotonic(), until, "the stalled hook never ended")
            time.sleep(0.05)
        # read without waiting: the FIFO, were it left as the receipt, holds what A's hook wrote
        receipt = os.open(self.receipt / "session", os.O_RDONLY | os.O_NONBLOCK)
        try:
            self.assertEqual(os.read(receipt, 4096).decode(), B)
        finally:
            os.close(receipt)


if __name__ == "__main__":
    unittest.main()

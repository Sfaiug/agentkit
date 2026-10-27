// hooks/opencode-seat/index.js -- the seat-state facts for an OpenCode seat.
//
// An OpenCode 2.0.14 plugin (the v2 shape: a default-exported {id, setup}), installed per
// launch: adapters/opencode.sh `interactive` names this directory in OPENCODE_CONFIG_CONTENT,
// beside the rulebook, so every seat carries that launch's hooks and nothing is written into
// the user's own ~/.config/opencode.  The package.json beside this file pins ESM: without
// `"type": "module"` the imports below load only where Node auto-detects module syntax, and
// an older Node would fail the plugin and silently cost the seat its hooks.  Headless worker
// turns never load it -- the launch variable is dropped from every run environment -- and
// where one still does (a hand run from a seat's own shell), hooks/seat-state.sh writes
// nothing without $AGENTKIT_SESSION.
//
// What it reports, translated to the one protocol hooks/seat-state.sh speaks for every
// harness (adapters/opencode.toml maps the names to states):
//   session.inbox.enqueued where the item is a user message -> UserPromptSubmit, with its text
//   session.execution.{succeeded,failed}                   -> Stop, with the session id and
//     the background work the harness records for it still running; none for a subagent's
//     session (`recorded`)
//   session.execution.interrupted                         -> Interrupt, with the session id
//   permission.asked                                         -> PermissionRequest, with the
//     action as the kind (a seat opened with --auto is never asked, but the fact is wired
//     for one opened without it)
// session.renamed also restores ak's title below; deltas and config updates are ignored.
//
// And before the `question` tool opens its dialog, the gate hooks/orchestrator-stop.sh is asked
// whether a finished seat's question is refused (`stop.question_refused`), as a PreToolUse hook
// asks it: the reason it gives is thrown, which 2.1.1 hands the model as the tool's error.
//
// And the session the seat is talking in, for the seat to come back to: where a prompt goes in,
// its id is written into this launch's receipt, the directory agentkit/harness/opencode.py
// named in $AGENTKIT_OPENCODE_RECEIPT.  A subagent's session is never the seat's: OpenCode's
// own record of it names its parent, and nothing of it is written.
//
// Every failure is silent: a hook that fails loudly is a harness that stops.
import { spawnSync } from "node:child_process";
import { readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The hook beside this plugin in the checkout, whatever directory the seat runs from.
const SEAT_STATE = fileURLToPath(new URL("../seat-state.sh", import.meta.url));
// The end-of-turn gate, which also answers whether the seat may ask.
const GATE = fileURLToPath(new URL("../orchestrator-stop.sh", import.meta.url));
// This launch's receipt, or none where the seat was not opened by agentkit.
const RECEIPT = process.env.AGENTKIT_OPENCODE_RECEIPT || "";
// The harness (2.1.1) runs its plugins on Bun 1.4.2, which offers Node's SQLite module.  A
// runtime offering none leaves its record unread.
const sqlite = await import("node:sqlite").catch(() => null);

function send(payload) {
  // Synchronously: an end-of-turn fact handed to a background child races the server's own
  // shutdown and loses, while a hundred milliseconds of hook runtime costs the event stream
  // nothing -- these events observe, they never gate.  hooks/seat-state.sh reads its JSON on
  // stdin and always exits 0; a hook that cannot be handed its fact says nothing at all.
  try {
    spawnSync(SEAT_STATE, [], { input: JSON.stringify(payload),
      stdio: ["pipe", "ignore", "ignore"], timeout: 5000 });
  } catch {
    // The hook left before its fact arrived; nothing here re-sends one.
  }
}

// Why the seat's question goes nowhere, or null where it may ask: the gate's PreToolUse answer,
// in PreToolUse's spelling.  A gate that cannot answer lets the question through.
export function refusal() {
  try {
    const run = spawnSync(GATE, [], {
      input: JSON.stringify({ hook_event_name: "PreToolUse", tool_name: "question" }),
      encoding: "utf8", stdio: ["pipe", "pipe", "ignore"], timeout: 10000 });
    const answer = JSON.parse(run.stdout || "null")?.hookSpecificOutput;
    return answer?.permissionDecision === "deny"
      && typeof answer.permissionDecisionReason === "string"
      ? answer.permissionDecisionReason : null;
  } catch {
    return null;
  }
}

function keep(sessionID) {
  // Whole or not at all: the id is written beside the last one and renamed over it, so a seat
  // killed or refused mid-write still holds its last good id.  Only into the launcher's own
  // directory, never a new one: a seat stopped since has had it removed, and a late fact must
  // not bring it back.
  if (!RECEIPT) return;
  const next = join(RECEIPT, "session.next");
  try {
    writeFileSync(next, sessionID);
    renameSync(next, join(RECEIPT, "session"));
  } catch {
    // Nothing written: the receipt says what it said before.
  }
}

// The plugin owns the API connection, so naming never types into a composer. The receipt
// pairs a request generation with the prompted session: a late reply or an earlier use of
// the same name cannot confirm a newer request. Polling also catches ak renames at idle.
// A tick whose applied file already confirms its request is quiet: no API call, no write.
// A rename event always verifies, since the title may have changed under a matching ack.
function titleSync(ctx) {
  let busy = false;
  let queued = false;
  async function run(verify = false) {
    if (!RECEIPT) return;
    if (busy) {
      if (verify) queued = true;
      return;
    }
    busy = true;
    try {
      const request = readFileSync(join(RECEIPT, "title-request.json"), "utf8");
      const { title, id } = JSON.parse(request);
      const sessionID = readFileSync(join(RECEIPT, "session"), "utf8").trim();
      if (typeof title !== "string" || !title.trim() || typeof id !== "string"
        || !/^ses_[0-9A-Za-z]+$/.test(sessionID)) return;
      if (!verify && confirmed(title, id, sessionID)) return;
      let info = await ctx.session.get({ sessionID });
      if (info?.id !== sessionID || info.parentID != null) return;
      if (info.title !== title) {
        rmSync(join(RECEIPT, "title-applied.json"), { force: true });
        await ctx.session.update({ sessionID, title });
        info = await ctx.session.get({ sessionID });
      }
      if (info?.id !== sessionID || info.title !== title || info.parentID != null
        || readFileSync(join(RECEIPT, "session"), "utf8").trim() !== sessionID
        || readFileSync(join(RECEIPT, "title-request.json"), "utf8") !== request) return;
      if (confirmed(title, id, sessionID)) return;
      const next = join(RECEIPT, "title-applied.next");
      writeFileSync(next, JSON.stringify({ title, id, sessionID }));
      renameSync(next, join(RECEIPT, "title-applied.json"));
    } catch {
      // A missing receipt or a refused update waits for the next tick, never a typed retry.
    } finally {
      busy = false;
      if (queued) {
        queued = false;
        await run(true);
      }
    }
  }
  return run;
}

// Whether the applied file already confirms this request on this session: the shape
// agentkit/harness/opencode.py accepts, exactly, so a stale or foreign ack never quiets.
function confirmed(title, id, sessionID) {
  try {
    const applied = JSON.parse(readFileSync(join(RECEIPT, "title-applied.json"), "utf8"));
    return applied !== null && typeof applied === "object" && applied.title === title
      && applied.id === id && applied.sessionID === sessionID
      && Object.keys(applied).length === 3;
  } catch {
    return false;
  }
}

// That Stop once the harness's own record of its session is read.  A subagent's session names
// its parent there, and its end is no end of the seat's turn: sent, it would read the seat as
// stopped while its turn goes on, dropping the work the seat holds.  Any other Stop goes with
// the background work still running for its session, as the `background_tasks` every harness's
// Stop hands over (`lifecycle.handed_over`): from the moment a background shell or subagent
// leaves its turn until its end is handed back, the harness keeps a
// `job.background/<notification>` row in its database's kv table (Job.background), `running`
// until it ends.  The plugin API reads neither.  A process that dies leaves its rows `running`:
// 2.1.1 resumes or cancels them only when it starts as the managed service (SessionRestart),
// never standalone, as a seat runs.  Every write stamps the row's time_updated, so a row last
// written before this process began is a dead one's, and none of its work runs.  A record that
// cannot be read leaves the Stop as it is: unread work is no evidence that none is running.
// The database is found where the harness itself finds it.
function recorded(stop) {
  if (!sqlite) return stop;
  const share = process.env.XDG_DATA_HOME || join(homedir(), ".local/share");
  const file = resolve(share, "opencode", process.env.OPENCODE_DB || "opencode.db");
  let db;
  try {
    db = new sqlite.DatabaseSync(file, { readOnly: true });
    const parent = db.prepare("SELECT parent_id FROM session_v2 WHERE id = ?");
    if (parent.get(stop.session_id)?.parent_id) return null;
    const jobs = db.prepare("SELECT value FROM kv WHERE key LIKE 'job.background/%' "
      + "AND time_updated >= ?").all(Math.floor(performance.timeOrigin));
    const work = [];
    for (const { value } of jobs) {
      const job = JSON.parse(value);
      const how = job?.status === "running" ? job.recovery : null;
      if (how?.kind === "shell" && how.sessionID === stop.session_id) {
        work.push({ id: how.shellID, type: "shell", status: "running",
          description: how.command, command: how.command });
      } else if (how?.kind === "subagent" && how.parentSessionID === stop.session_id) {
        work.push({ id: how.childSessionID, type: "subagent", status: "running",
          description: how.description, agent_type: how.agent });
      }
    }
    return { ...stop, background_tasks: work };
  } catch {
    return stop;
  } finally {
    db?.close();
  }
}

// The session that event shows a prompt going into, or null.  Only a prompt says which
// conversation the seat is in: an older turn still running ends whenever it ends, and its end
// must not take the seat back from the session prompted since.
function promptedSession(event) {
  if (event === null || typeof event !== "object") return null;
  const data = event.data;
  if (data === null || typeof data !== "object" || typeof data.sessionID !== "string") return null;
  return event.type === "session.inbox.enqueued"
    && data.item !== null && typeof data.item === "object" && data.item.type === "user"
    ? data.sessionID : null;
}

// Whether the harness's own record of that session says it is the seat's conversation: a
// subagent's names the session that started it as its parent, whenever and however it was
// started.  A record that cannot be read is not the seat's, and the last good id stands.
async function own(ctx, sessionID) {
  try {
    const info = await ctx.session.get({ sessionID });
    return info !== null && typeof info === "object" && info.id === sessionID
      && (info.parentID === undefined || info.parentID === null);
  } catch {
    return false;
  }
}

// The fact one harness event becomes, or null when the seat does not report it.
export function seatFact(event) {
  if (event === null || typeof event !== "object") return null;
  const data = event.data;
  if (data === null || typeof data !== "object") return null;
  if (event.type === "session.inbox.enqueued"
    && data.item !== null && typeof data.item === "object"
    && data.item.type === "user"
    && data.item.payload !== null && typeof data.item.payload === "object"
    && typeof data.item.payload.text === "string") {
    return { hook_event_name: "UserPromptSubmit", message: data.item.payload.text };
  }
  if ((event.type === "session.execution.succeeded"
    || event.type === "session.execution.failed"
    || event.type === "session.execution.interrupted")
    && typeof data.sessionID === "string") {
    return { hook_event_name: event.type === "session.execution.interrupted" ? "Interrupt" : "Stop",
      session_id: data.sessionID };
  }
  if (event.type === "permission.asked" && typeof data.action === "string") {
    const resources = Array.isArray(data.resources)
      ? data.resources.filter((name) => typeof name === "string") : [];
    return { hook_event_name: "PermissionRequest", tool_name: data.action,
      message: [data.action, ...resources].join(" ") };
  }
  return null;
}

export default {
  id: "agentkit.seat",
  async setup(ctx) {
    console.log("[agentkit.seat] reporting seat-state facts to hooks/seat-state.sh");
    const controller = new AbortController();
    // A version with no tool hook asks as it always did.
    const gate = Promise.resolve()
      .then(() => ctx.tool.hook("execute.before", (call) => {
        if (call?.tool !== "question") return;
        const reason = refusal();
        if (reason) throw new Error(reason);
      }))
      .catch(() => null);
    const syncTitle = titleSync(ctx);
    const timer = setInterval(syncTitle, 1000);
    timer.unref();
    void syncTitle();
    // Prompt session ids, kept in event order, never holding a fact: a stuck session call
    // delays only the keeps behind it, while each fact is sent below without waiting.
    let keeping = Promise.resolve();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          try {
            const sid = promptedSession(event);
            if (sid) {
              keeping = keeping.then(async () => {
                try {
                  if (await own(ctx, sid)) {
                    keep(sid);
                    void syncTitle();
                  }
                } catch {
                  // One session that cannot be kept costs that keep, never the chain.
                }
              });
            }
            // Generated and owner titles use this same event in 2.0.14. Both give way
            // to ak's name; neither is evidence that the owner renamed the seat.
            if (event.type === "session.renamed") void syncTitle(true);
            const fact = seatFact(event);
            const sent = fact?.hook_event_name === "Stop" ? recorded(fact) : fact;
            if (sent) send(sent);
          } catch {
            // One fact that cannot be shaped costs that fact, never the subscription.
          }
        }
      } catch {
        // The stream ended, the server with it; the cleanup below runs on unload.
      }
    })();
    return () => {
      clearInterval(timer);
      controller.abort();
      gate.then((hook) => hook?.dispose?.()).catch(() => {});
    };
  },
};

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
//   session.execution.{succeeded,failed,interrupted}        -> Stop, with the session id and
//     the context total the last step reported, for the idle-compact stamp
//   permission.asked                                         -> PermissionRequest, with the
//     action as the kind (a seat opened with --auto is never asked, but the fact is wired
//     for one opened without it)
// session.renamed also restores ak's title below; deltas and config updates are ignored.
//
// And the session the seat is talking in, for the seat to come back to: where a prompt goes in,
// its id is written into this launch's receipt, the directory agentkit/harness/opencode.py
// named in $AGENTKIT_OPENCODE_RECEIPT.  A subagent's session is never the seat's: OpenCode's
// own record of it names its parent, and nothing of it is written.
//
// Every failure is silent: a hook that fails loudly is a harness that stops.
import { spawnSync } from "node:child_process";
import { readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// The hook beside this plugin in the checkout, whatever directory the seat runs from.
const SEAT_STATE = fileURLToPath(new URL("../seat-state.sh", import.meta.url));
// This launch's receipt, or none where the seat was not opened by agentkit.
const RECEIPT = process.env.AGENTKIT_OPENCODE_RECEIPT || "";

function number(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function stepTotal(tokens) {
  if (tokens === null || typeof tokens !== "object") return null;
  const cache = tokens.cache !== null && typeof tokens.cache === "object" ? tokens.cache : {};
  // Session totals count output and reasoning apart (a turn's output never includes its
  // reasoning), so both are summed: with input and the cache, that is what the next turn
  // starts on.  See the `run` usage note in adapters/opencode.sh.
  return (number(tokens.input) + number(tokens.output) + number(tokens.reasoning)
    + number(cache.read) + number(cache.write));
}

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

// Whether OpenCode's own record of that session says it is the seat's conversation: a
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

// The fact one OpenCode event becomes, or null when the event is not one of the three
// the seat reports. `lastStep` remembers a step's context total until the turn ends.
export function seatFact(event, lastStep) {
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
  if (event.type === "session.step.ended" && typeof data.sessionID === "string") {
    const total = stepTotal(data.tokens);
    if (total !== null && lastStep) lastStep.set(data.sessionID, total);
    return null;
  }
  if ((event.type === "session.execution.succeeded"
    || event.type === "session.execution.failed"
    || event.type === "session.execution.interrupted")
    && typeof data.sessionID === "string") {
    // A turn that never finished a step reports no size: the stamp is skipped the
    // way an unreadable transcript is, and the last good one stands.
    const stop = { hook_event_name: "Stop", session_id: data.sessionID };
    if (lastStep && lastStep.has(data.sessionID)) {
      stop.context_tokens = lastStep.get(data.sessionID);
      lastStep.delete(data.sessionID);
    }
    return stop;
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
    const lastStep = new Map(); // session id -> context total of its latest finished step
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
            const fact = seatFact(event, lastStep);
            if (fact) send(fact);
          } catch {
            // One fact that cannot be shaped costs that fact, never the subscription.
          }
        }
      } catch {
        // The stream ended, the server with it; the cleanup below runs on unload.
      }
    })();
    return () => { clearInterval(timer); controller.abort(); };
  },
};

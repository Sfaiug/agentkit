"""The judgement of an orchestrator seat's turn's end: whether its Stop stands or goes back,
and whether its question prompt goes up.

`judge` hides how: the turn's latch and block counter, the transcript in each harness's shape,
the question asked or left in prose, and the Stop written down for the seat's row.
hooks/orchestrator-stop.sh has it run on every Stop and PreToolUse an orchestrator seat's
harness hands it, by the warm looker where one takes it (`looker.take`), and prints its answer.

An orchestrator turn ends in exactly one of three ways -- an unanswered question through the
harness's question prompt or `ak notify needs`, a run or live job it is waiting on, including
background work it started in its own harness, a command aside, while the harness still lists
it in flight, and a pull request, run or date it waits on by `ak wait`, for as long as
`watch.waiting_on` says that is not yet over.  A merged run of its own not yet live, where its project declares
`health:`, is ak's own step and a wait too.  With no open line in the seat's plan nothing is
owed, and a plain reply stands.  A run of its own that sits parked and undecided --
`unfinished`, so not one a later merged run replaced --
holds the turn past a finished plan or a run going: the block names each such run, its
parked reason and the commands its state takes, and the seat looks at it, resumes it,
relaunches it split or on another model, stops it, or asks the owner.  A question, `ak notify
needs`, background work and the third stop stand past it, as they always did.  An unnamed seat
is sent back to name itself instead, past everything but a question (`config.name_owed`).
Anything else is sent back to work with the harness's own block decision, which Claude Code
2.1.263, Codex 0.153.4 and Grok Build 1.0.40 spell the same way: `{"decision": "block",
"reason": "..."}` on stdout.  "Here is my recommendation, let me know if I should continue"
then costs the user nothing but one turn.  A turn that would end on a last message ending in
a question mark, with nothing asked through the question prompt or `ak notify needs`, is sent
back once: a question left in prose reaches nobody but the terminal, so the seat asks it there
or goes on without it.  So is a turn whose own ssh reached the live host and that leaves its plan
no open line (`stop.live_unrecorded`): what it did there is written down, or it only read.  So,
at every turn's end, is one of a seat with a done plan whose project's suite reports no tests to
ak (`stop.untested`): the seat writes that into its plan and builds it.

Before the harness draws its question prompt (PreToolUse, where its adapter installs it) this
refuses the question of a seat whose plan is done with nothing from the owner since
(`stop.question_refused`): it would block nothing but the owner, so its last message says it,
and a turn ending on it in prose stands.  Letting it through, it keeps each question the card
asks back for the turn's end, as every seat's own question is kept (`watch.keep`): the owner's
answer on the card drops it as their time (`watch.answered_kept`), and a card that answered
nothing has it asked when the turn ends.

It blocks at most twice in one turn, and once more for a question left in prose; a done plan on
a project whose suite reports no tests goes back at every stop, which an open line ends.  The
counter lives beside the turn's own start in ~/.agentkit/state/stop-<seat>.json, which
hooks/seat-state.sh writes fresh on every UserPromptSubmit; the third stop stands, and one
with work open and nothing recorded becomes a question to the owner carrying the seat's last
words, so a model that truly cannot proceed is heard rather than looping forever.

On a harness that lists its background work this is also what writes the Stop down, in the
record hooks/seat-state.sh keeps for every other event: the two hooks run side by side, and only
this one knows whether the turn ended -- a stop sent back is `held`, one on background work is
`background`, and both are the turn going on.  hooks/seat-state.sh leaves such a Stop to this,
so no screen ever reads one before it has been judged.
"""

import json
import os

from . import config, harness, lifecycle, notify, questions, usage
from .handback import handback_reason
from .stop import live_unrecorded, question_refused, recorded_ending, untested, ways_out
from .watch import keep, start_look, turn_ended

LIMIT = 2           # blocks in one turn; the third stop stands
REASON = ("You stopped with work open and nothing recorded: no question asked through the question "
          "prompt or ak notify needs, no run or pull request you are waiting on, and an open line "
          "in your plan. Continue: decide the next step and do it. ak plan checks every open line "
          "and ticks the proven ones; nothing else ticks a line between runs. A background "
          "command is no wait: wait on a pull request or run with ak wait <PR url or run id>.")
ASK = ("Your last message ends in a question, but it went through no question prompt, so the "
       "owner is not told. Ask it through the question prompt (ak notify needs where there is "
       "none), or go on without it.")
STUCK = "How should this seat go on? It stopped three times with work open:"


def loads(text):
    try:
        data = json.loads(text or "")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def read(path):
    try:
        return loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def moment(value):
    """A timestamp, or None: a bool is an int and `true` is not a moment."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def resolve(name):
    """The name that seat goes by now: `ak orch rename` leaves a pointer at the old one.

    The launch name stays in $AGENTKIT_SESSION for the life of the seat, so the records this
    reads -- which moved with the rename -- are only found under the name at the end of it.
    A chain that does not resolve leaves the name as it is: a stop hook decides from what it
    can read and never fails the stop.
    """
    try:
        return config.resolve_session(name)
    except config.Error:
        return name


def spoken(entry):
    """The assistant text one transcript line holds, in whichever shape its harness writes.

    Claude Code writes `{"type": "assistant", "message": {"content": [...]}}`, Codex
    `{"payload": {"type": "message", "role": "assistant", "content": [...]}}`.  A sidechain is
    a sub agent talking to itself and never what this seat said to the user.
    """
    if entry.get("isSidechain"):
        return None
    if entry.get("type") == "PLANNER_RESPONSE" and isinstance(entry.get("content"), str):
        return entry["content"].strip() or None
    message = entry.get("message") if entry.get("type") == "assistant" else None
    payload = entry.get("payload")
    if (message is None and isinstance(payload, dict) and payload.get("type") == "message"
            and payload.get("role") == "assistant"):
        message = payload
    if not isinstance(message, dict):
        return None
    said = "\n".join(part["text"] for part in message.get("content") or []
                     if isinstance(part, dict) and isinstance(part.get("text"), str))
    return said or None


def transcript(payload):
    """Newest entries first, read back in growing chunks as far as the caller goes: a question
    still open stays found however much output followed it, in at most one chunk of memory."""
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    if not isinstance(path, str) or not path:
        return
    try:
        handle = open(path, "rb")
    except OSError:
        return
    with handle:
        end, chunk, rest = handle.seek(0, os.SEEK_END), 1 << 18, b""
        while end > 0:
            start = max(0, end - chunk)
            handle.seek(start)
            lines = (handle.read(end - start) + rest).split(b"\n")
            # the first line of a chunk that starts mid-file is half a line, read whole next time
            rest = lines.pop(0) if start else b""
            for line in reversed(lines):
                entry = loads(line)
                if not entry.get("isSidechain"):
                    yield entry
            end, chunk = start, min(chunk * 4, 1 << 26)


def last_message(payload):
    """Codex hands over the message; Claude names its transcript. Both key spellings occur."""
    for key in ("last_assistant_message", "lastAssistantMessage", "finalModelOutput"):
        if key in payload:
            said = payload[key]
            return said if isinstance(said, str) else None
    for entry in transcript(payload):
        said = spoken(entry)
        if said:
            return said
    return None


def questioned(payload):
    """Only an unanswered question still needs the owner; its result ends that wait.

    Input in the owner's words, as their harness tells them from its bookkeeping
    (`harness.prompt`), ends the scan: what was asked before it is answered or set aside.
    An async card is not read here: ak records it before its harness draws it (the plugin's
    `ask`), and that record says whether it stands, taken back too.
    """
    answered = set()
    for entry in transcript(payload):
        item = entry.get("payload")
        item = item if isinstance(item, dict) else {}
        if harness.prompt(entry) is not None:
            return False
        message = entry.get("message")
        message = message if isinstance(message, dict) else item
        content = message.get("content") or []
        if isinstance(content, list):
            answered.update(part.get("tool_use_id") for part in content
                            if isinstance(part, dict) and part.get("type") == "tool_result"
                            and isinstance(part.get("tool_use_id"), str))
        if item.get("type") == "function_call_output" and isinstance(item.get("call_id"), str):
            answered.add(item["call_id"])
        if entry.get("type") == "assistant" and isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") == "tool_use"
                and part.get("name") == "AskUserQuestion"
                and part.get("id") not in answered
                for part in content):
            return True
        name = item.get("name")
        tool = name.rsplit(".", 1)[-1] if isinstance(name, str) else ""
        if (item.get("type") == "function_call" and tool == "request_user_input"
                and item.get("call_id") not in answered):
            return True
    return False


def trails_question(said):
    """The message ends in a question mark, past any closing emphasis, quote or bracket."""
    return (said or "").rstrip().rstrip("*_`'\"’”»)]}").endswith("?")


def told(seat, turn):
    """`ak notify needs` asked for this seat during the turn, and it stands: one taken back
    (`ak notify settled`) asks nobody."""
    note = notify.last(seat) or {}
    when = moment(note.get("time"))
    return (when is not None and when >= turn
            and any(not q.startswith(STUCK) for q in notify.questions(note)))


def parked_reason(found):
    """The block where runs sit parked and undecided: each run, its reason and the commands its
    state takes -- `ways_out`, so none that refuses it -- and the ways out."""
    runs = "; ".join(f"run {directory.name} parked: {handback_reason(state)} "
                     f"({' / '.join(ways_out(state, directory))})"
                     for directory, state in found)
    return (f"{runs}. Continue: settle each with one of its commands -- ak run status marks an "
            f"ended run looked at, ak run resume carries it on, ak run stop ends it -- relaunch "
            f"it split or on another model, or ask the owner.")


def asked_owner(seat, said):
    """A third stop with work open and nothing recorded is a seat that cannot go on: its last
    words follow the question the owner is paged with, so the card says what it is stuck on.
    It is kept back as `ak notify needs` keeps one for its turn's end, which this stop is."""
    words = " ".join((said or "").split())
    if len(words) > 200:
        words = "\u2026" + words[-199:]        # the end, where what it is stuck on is said
    notify.keep_back(seat, f"{STUCK} {words}")


def unpark(launched, payload):
    """The login this Stop's harness runs on loses the refusals the turn it ends shows were
    wrong (`usage.answered`), where that login answered it; whatever fails here, the Stop is
    judged, written down and answered as without it.

    On 19 Nov 2026 a login 25% used was parked for an hour while it answered the owner: "even
    this session says out of usage".  Asked on 20 Nov whether ak should unpark an account as
    soon as a session finishes a turn on it, the owner said "Yes, build it"; on 21 Nov, after
    designs failed review, "Keep trying".  An answered turn is a fact about the past, whole
    when its Stop is judged, and heard exactly only here: once for each Stop, in its harness's
    own environment, whose AGENTKIT_ACCOUNT names the login it runs on (`config.account_env`).
    A later look at the seat finds another hook, a prompt, a move or a second wait come
    between, and so does a second read of its record, which a move leaves naming another login:
    so each thing is read once, in this order, and the record's harness is asked what
    `watch.recorded_error` and `watch.limit_ended` ask, on that one record -- both read it
    again, and the plan `limit_ended` asks writes.

    That 19 Nov turn was a long one, its login parked while it ran.  Asked on 22 Nov whether
    this should stay with turns begun after the parking, the owner: "Keep building", for a turn
    already running, "judged by when its last request was sent".  The harness fires Stop once
    the model has finished responding (StopFailure for a request that failed), and writes a
    request line on the record before that request's answer, after any tool's result its
    message before asked for: on 25 Nov 2026 (version 2.1.332, a turn running `sleep 15`), the
    owner's words at 18:21:11.999, request 12.389 (0.39 s later), tool call 15.344, result
    30.892, request 31.021 (0.13 s later), answer 32.178, with the Stop hook starting before
    the answer's entry was written 0.1 s later.  Asked on 26 Nov whether to drop that 0.13 s /
    0.39 s window between result (or prompt) and request, the owner: "Build it".  So the
    refusals that go are those made before the later of the turn's start and that request, or
    the last tool's result outside a sidechain where the record holds no request line
    (`last_request`, its plugin's), asked last of the same record: no answer shows one made
    after it wrong.

    On 26 Nov 2026, tried on a real seat on a parked login answering a real turn, Codex
    0.172.0 unparked its provider at the turn's Stop, while Grok Build 1.0.92 and Antigravity
    1.5.18 each answered, their Stop was judged, and the login stayed parked: neither plugin
    keeps a record of errors (`keeps_errors`).  The owner, 26 Nov 2026, of what was built for
    Claude Code: "I want you to also apply to every other harness. All should work the same
    way with ak."  What `keeps_errors` guards is a Stop heard for a refused turn: Antigravity
    names an error ending in `terminationReason` (its hooks documentation, 1.5.18), already
    returned on above, and Grok Build runs StopFailure and no Stop for a refused turn
    (observed 6 Nov 2026, 1.0.46, its `updates.jsonl`: `hook_execution` `stop_failure`, then
    nothing until the session ended).  So `error` and `wrapped_up` are asked only where the
    harness keeps errors; where it keeps none, a Stop past that first check unparks as well,
    dated by `last_request` where the plugin has one else the turn's start.
    """
    try:
        if (payload.get("terminationReason") not in (None, "", "NO_TOOL_CALL")
                or last_message(payload) is None):
            return      # as `held` reads it: no turn ending on words it can read
        turn = moment(read(config.stop_path(launched)).get("turn"))
        if turn is None:
            return
        cfg = config.load()
        record = config.resolved_record(launched) or {}
        entry = config.model(cfg, record.get("orchestrator"))
        told = os.environ.get(config.ACCOUNT_ENV, "")
        if config.account_env(record.get("account"))[config.ACCOUNT_ENV] != told:
            return
        plugin = harness.load(entry["harness"])
        sent = None
        if plugin.keeps_errors or getattr(plugin.module, "last_request", None):
            # only look up the conversation when a reader needs it: antigravity's claims under a lock
            cwd = record.get("cwd")
            conversation = plugin.conversation(record, cwd)
            if plugin.keeps_errors and (
                    plugin.error(record, cwd, conversation) != ""
                    or plugin.wrapped_up(record, cwd, conversation) is not None):
                return
            sent = plugin.last_request(record, cwd, conversation)
        usage.answered(cfg, entry["provider"], told or None, record["orchestrator"],
                       turn if sent is None else max(turn, sent))
    except Exception:
        pass        # the login stays parked as it was; the Stop is no less judged


def held(launched, payload, records=None):
    """The reason to send this stop back with, or "" where the stop stands.

    At most LIMIT blocks in one turn, which the latch counts: a question, `ak notify needs`,
    background work and the third stop stand past a parked run as they always did, while a
    finished plan, a run going, a merged run not yet live or an `ak wait` ends the turn only with none
    of this seat's runs parked and undecided, and nothing at all is owed with no open line in
    the seat's plan.  A turn that ends so on a question in prose alone goes back once to ask it,
    and one that reached the live host with no open line once to write it down; neither counts.
    One that `stop.untested` names goes back at every stop, counting none.
    """
    if payload.get("terminationReason") not in (None, "", "NO_TOOL_CALL"):
        return ""    # agy's cancelled or error terminations are not a turn ending on its words
    # The latch is this seat's own file, under the name its harness was launched with, the way
    # hooks/seat-state.sh writes it.  What it reads is the toolkit's, and that moved when the
    # seat was renamed.
    latch = config.STATE / f"stop-{launched}.json"
    record = read(latch)
    turn = moment(record.get("turn"))
    if turn is None:
        return ""    # no turn was written down; nothing here can say what happened during it
    seat = resolve(launched)
    # ak's third-stop question is no fact of the seat's own. Once the seat can end on one,
    # retire that question before asking it to repeat its still-unanswered questions in chat.
    pending = questions.pending(seat)
    asked = (questioned(payload) or told(seat, turn)
             or any(not q.startswith(STUCK) for q in pending))
    ends, undecided = recorded_ending(seat, records, question=asked, since=turn)
    if any(q.startswith(STUCK) for q in pending):
        if ends or lifecycle.waits_on(payload):
            notify.clear(seat, prefix=STUCK, wait=False)
        else:
            return ""    # still stuck: the owner was asked once, and nothing has changed
    pending = [q for q in questions.pending(seat) if q.startswith(STUCK)]
    delivery = questions.reminder(seat, last_message(payload))
    if pending:
        for question in pending:
            delivery = delivery.replace("\n\n" + question, "", 1)
        if "\n\n" not in delivery:
            delivery = ""
    if not delivery and lifecycle.waits_on(payload):
        return ""
    if not delivery and last_message(payload) is None:
        return ""    # nothing it said can be read; nothing here can judge the turn
    if ends and not delivery:
        live = not asked and not record.get("live_back") and live_unrecorded(launched)
        if live:
            config.write_latch(latch, {**record, "live_back": True})
            return live
        owes = not asked and untested(seat)
        if owes:
            return owes     # at every stop, past the turn's blocks: nothing is kept
        if (asked or record.get("asked_back") or not trails_question(last_message(payload))
                or question_refused(seat)):
            return ""
        config.write_latch(latch, {**record, "asked_back": True})
        return ASK
    blocks = record.get("blocks")
    blocks = blocks + 1 if isinstance(blocks, int) and not isinstance(blocks, bool) else 1
    if blocks > LIMIT:
        if not ends and not undecided:
            asked_owner(seat, last_message(payload))
        return ""    # the third stop stands: the owner is paged with what the seat is stuck on
    config.write_latch(latch, {**record, "session": launched, "turn": turn, "blocks": blocks})
    return delivery or (parked_reason(undecided) if undecided else config.name_owed(seat) or REASON)


def written(launched, payload, held):
    """This Stop (`lifecycle.stop_fact`), as hooks/seat-state.sh writes every other event down
    for the seat's row: under the name the seat goes by now, which is the name its row reads,
    and in the order the two hooks heard their events (`config.record_hook_fact`)."""
    try:
        fact = lifecycle.stop_fact(launched, payload, config.heard_at(launched), held)
        config.record_hook_fact(resolve(launched), fact)
    except (OSError, config.Error):
        pass        # a Stop nobody could write down is no reason to let the turn end


def judge(launched, payload, records=None):
    """What the hook prints for the seat launched as `launched` on `payload`, its harness's
    JSON as handed over: the block decision, the refusal of a question, or "" for nothing.
    `records` are the runs judged on (`stop.recorded_ending`), read here where none are given.
    A Stop first unparks the login that answered the turn it ends (`unpark`)."""
    payload = loads(payload)
    if payload.get("hook_event_name") == "PreToolUse":
        seat = resolve(launched)
        refused = question_refused(seat)
        if refused:
            return json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": refused}}) + "\n"
        call = payload.get("tool_input")
        listed = call.get("questions") if isinstance(call, dict) else None
        for item in listed if isinstance(listed, list) else ():
            text = item.get("question") if isinstance(item, dict) else None
            if isinstance(text, str) and text.strip():
                keep(seat, text)
        return ""
    unpark(launched, payload)
    back = held(launched, payload, records)
    if not back:
        # the stop stands: the turn a kept question was asked in has ended, and that is on
        # record before this harness takes its next prompt (`watch.turn_ended`)
        turn_ended(resolve(launched))
    # a harness that lists none has its stops judged, and written down, as before
    if lifecycle.handed_over(payload) is not None:
        written(launched, payload, bool(back))
        # looked at again now its Stop is on record, however long judging it took
        start_look(launched)
    return json.dumps({"decision": "block", "reason": back}) + "\n" if back else ""

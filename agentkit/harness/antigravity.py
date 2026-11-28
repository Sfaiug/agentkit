"""Antigravity: the conversation a seat holds, read back for a model taking the seat over, and
ended, with what every home keeps of it, once `ak gc` finds it stale.

agy's TUI cannot be handed an id for a new conversation, so a seat's is learned rather than
issued: each launch carries a token of its own in its environment, and the conversation a
process carrying it holds open is that launch's (agy 1.4.7 makes `<id>.db` within seconds and
holds it, its -wal and -shm open while it runs).  A host whose processes' open files cannot be
read gives a seat none, as before.  From there the seat follows each conversation its agy takes
a prompt in (`follow`), as /clear opens a new one in the same process.

agy keeps each conversation as a SQLite database of its own, ~/.gemini/antigravity-cli/
conversations/<id>.db, where every login's are (adapters/antigravity.sh links them): one row
per step, its `step_payload` a protocol buffer.  agy ships no schema for it; the numbers below
were read off agy 1.2.13's own databases.
"""

import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .. import config, look
from . import LAUNCHER, issued

# `steps.step_type`, and where each keeps its words in its payload: a user input's text, and
# a planner response's answer -- its thinking (3) and tool calls (7) are fields beside that.
# A question card `ask_question` put up keeps its answer in its own step (`answers`), and a
# compaction, one more model call, its usage in its own (`seat_token_usage`).
USER, MODEL, CARD, COMPACTION = 14, 15, 132, 23
WORDS = {USER: ("user", 19, 2), MODEL: ("model", 20, 1)}
LAUNCH_ENV = "AGENTKIT_ANTIGRAVITY_LAUNCH"
# what a model call's `usage` counts, in the order a `turn_usage` row keeps them, less the cache
# write agy never reports
TOKEN_KINDS = ("input_tokens", "cache_read_tokens", "output_tokens")
SOURCE = "antigravity-hook"   # `id_source`: a conversation the seat's own agy took a prompt in
VARINT = 0                    # the wire type of a protocol buffer's number, as `field` reads it
PROC = Path("/proc")


def launched(name, cwd, conversation):
    """A resumed conversation is the launcher's id; a new one is learned under this token."""
    token = uuid.uuid4().hex
    issued(name, conversation, antigravity_launch=token, antigravity_open=None)
    return {LAUNCH_ENV: token}


def conversation(record, cwd=None):
    """The conversation the record gives this seat, else the one its launch's own agy holds
    open, written down beside that launch's token so it outlives the process and a stale
    launch's is never a later one's.  One another seat's record names is never this one's, nor
    a guess between two."""
    mine, token = owned(record), record.get("antigravity_launch")
    if mine or not isinstance(token, str):
        return mine
    # One claim at a time, from the records as they stand: a caller's copy may predate this
    # launch's claim, and another seat's may land while the fds are read.
    from . import named_elsewhere, unread
    with contextlib.ExitStack() as held:
        try:
            held.enter_context(learning())
        except OSError as exc:
            unread(exc)
            return None
        # on the disk now: a menu's pass asks this with the records it first read, from before
        # a claim another seat made since, and would take that seat's conversation beside it
        held.enter_context(look.aside())
        records = config.session_records()
        name = next((name for name, kept in records.items()
                     if kept.get("antigravity_launch") == token), None)
        mine = owned(records.get(name, {}))
        if name is None or mine:
            return mine
        found = held_open(token) - named_elsewhere(records, name)
        if len(found) != 1:
            return None
        found = found.pop()
        config.update_session(name, antigravity_open={"launch": token, "conversation": found})
        return found


@contextlib.contextmanager
def learning():
    """The lock a launch's conversation is learned under (`conversation`), and a seat's prompt
    claims one under (`follow`): Go's ak learns under it too."""
    with open(config.STATE / "antigravity-claim.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def owned(record):
    """What that record alone says its seat owns: a launcher's id, one its agy took a prompt in
    (`follow`), or one its launch saw."""
    if record.get("id_source") in (LAUNCHER, SOURCE):
        return record.get("conversation")
    seen = record.get("antigravity_open")
    if isinstance(seen, dict) and seen.get("launch") == record.get("antigravity_launch"):
        return seen.get("conversation")
    return None


def follow(launched, payload, pid):
    """A prompt the seat's own agy took in another conversation than the seat's moves the seat
    there (`claim`), whoever typed it: /clear opens a new one in the same process, and only its
    next prompt names it.  The launch's PreInvocation hook hands on agy's `conversationId` as
    `session_id` (adapters/antigravity.sh `interactive`), the id `--conversation` reopens
    `<id>.db` by, so one with no database in agy's store is no conversation to follow."""
    from .. import orch
    from . import claim
    if isinstance(payload, dict) and payload.get("hook_event_name") == "UserPromptSubmit":
        found = store(payload.get("session_id"))
        claim(launched, "antigravity", payload.get("session_id"),
              str(found) if found and found.is_file() else None,
              lambda record, conversation: store(conversation), pid,
              lambda words: orch.program(words) == "agy", id_source=SOURCE)


def resumable(record, cwd, conversation):
    """A conversation the seat owns is one `--conversation` reopens it on."""
    return bool(conversation)


def reconcile(record):
    """A conversation the record names and the seat does not own (`owned`) is not its to resume."""
    return ({"conversation": None, "resumable": False}
            if record.get("conversation") and owned(record) != record["conversation"] else {})


def held_open(token):
    """The conversations a process carrying that launch's token has its .db open of."""
    want, root, found = f"{LAUNCH_ENV}={token}".encode(), conversation_stores()[0]["root"], set()
    try:
        pids = [entry for entry in os.listdir(PROC) if entry.isdigit()]
        root = root.resolve()
    except OSError:
        return found
    for pid in pids:
        try:
            if want not in (PROC / pid / "environ").read_bytes().split(b"\0"):
                continue
            fds = list((PROC / pid / "fd").iterdir())
        except OSError:      # gone meanwhile, or not ours to read
            continue
        for fd in fds:
            try:
                path = Path(os.readlink(fd))
            except OSError:
                continue
            if path.parent == root and path.suffix == ".db" and re.fullmatch(r"[\w-]+",
                                                                             path.stem):
                found.add(path.stem)
    return found


def turn_usage(out):
    """The turn's own counts, the sum of each model call's `usage` its stream's `step_update`s
    give, under the model the worker launched it with (`launched_model`), as
    `Harness.turn_usage` gives them: none where no call reported one.

    agy counts a call's thinking inside its `output_tokens`, its cached input beside its
    `input_tokens` (`cache_read_tokens`, in neither that nor `total_tokens`), and writes no
    cache.  The closing `result` totals every turn the conversation has had, so is not read.
    """
    from . import launched_model
    calls = []
    try:
        with (Path(out) / "events.jsonl").open(errors="replace") as stream:
            for line in stream:
                try:
                    usage = json.loads(line)["step_update"]["usage"]
                except (ValueError, TypeError, KeyError):
                    continue
                if isinstance(usage, dict):
                    calls.append([count if type(count := usage.get(key)) is int and count >= 0
                                  else 0 for key in TOKEN_KINDS])
    except OSError:
        return None
    if not calls:
        return None
    fresh, cached, output = map(sum, zip(*calls))
    return None, False, {launched_model(out): (fresh, 0, cached, output)}


def seat_token_sources(record):
    """The store of each conversation the seat had on agy, each it left (`claim`) under the login
    it was left on and the one it owns (`owned`): every model call keeps its usage in a step of
    its own there (`seat_token_entries`), and /clear may leave one between two readings.  An
    entry kept without a login was left on the record's (`notify.left`)."""
    login = record.get("account")
    had = [(was.get("conversation"), was.get("account", login)) for was in record.get("left") or ()
           if isinstance(was, dict) and was.get("harness") == "antigravity"]
    return [(found, account) for conversation, account in [*had, (owned(record), login)]
            if (found := store(conversation))]


def seat_token_entries(path):
    """Each step of that store keeping a model call's usage, a compaction's as well, read whole,
    as (its metadata, the name of each model the store numbers): a generation's `gen_metadata`
    names its model at 1 -> 19, beside the number (1 -> 4 -> 1) a call's usage names it by
    (`seat_token_usage`).  OSError where any of it cannot be read: a call is filed once, so
    never without the names beside it."""
    try:
        with contextlib.closing(sqlite3.connect(f"{Path(path).absolute().as_uri()}?mode=ro",
                                                uri=True)) as db:
            calls = db.execute("SELECT metadata FROM steps WHERE step_type IN (?, ?) ORDER BY idx",
                               (MODEL, COMPACTION)).fetchall()
            # after the calls, so a generation written meanwhile names its call; an older store
            # keeps no table of them
            kept = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'gen_metadata'").fetchone()
            named = db.execute("SELECT data FROM gen_metadata").fetchall() if kept else ()
    except sqlite3.Error as exc:
        raise OSError(f"cannot read {path}: {exc}") from exc
    names = {}
    for data, in named:
        generation = field(data, 1)
        if name := decoded(field(generation, 19)):
            names[field(field(generation, 4), 1, VARINT)] = name
    return [(metadata, names) for metadata, in calls]


def seat_token_usage(entry, cursor):
    """A model call's usage, its step's metadata 9 (a failed call keeps none, or an empty one),
    filed by the response id agy gave the call (11), dated when its step finished (metadata 8)
    else began (1): its uncached input (2), cached input (5) and output, thinking inside (3),
    each 0 where left out as a protocol buffer leaves a 0, under the model its number (1) names.
    agy writes no cache.  An older store's compaction keeps its counts only at metadata 28 -> 2,
    laid out as 9 less the model's number, so its model is 9's where 9 numbers one."""
    metadata, names = entry
    usage, older = field(metadata, 9), field(field(metadata, 28), 2)
    model = names.get(field(usage, 1, VARINT))
    if older and not any(field(usage, kind, VARINT) for kind in (2, 5, 3)):
        usage = older
    call = decoded(field(usage, 11))
    if not call:
        return None
    fresh, cached, output = (field(usage, kind, VARINT) or 0 for kind in (2, 5, 3))
    at = timestamp(field(metadata, 8))
    counts = [fresh, 0, cached, output]
    return (timestamp(field(metadata, 1)) if at is None else at, call, sum(counts), model, counts)


def prompt(entry):
    """The owner's words one transcript line holds, or None for anything else."""
    content = entry.get("content")
    if entry.get("type") == "USER_INPUT" and isinstance(content, str) and content:
        return content.strip()
    return None


def said(record, cwd, conversation):
    found = steps(conversation, *WORDS)
    if found is None:
        return None
    said = []
    for kind, _metadata, payload in found:
        text = words(kind, payload)
        if text:
            said.append({"who": WORDS[kind][0], "text": text})
    return said


def user_messages(record, cwd, conversation):
    """Each user input, dated by its step's `metadata`: field 1 a Timestamp.  A step dated
    otherwise is nobody's answer."""
    from . import user_message
    for _kind, metadata, payload in steps(conversation, USER) or ():
        at = timestamp(field(metadata, 1))
        kept = at is not None and user_message(at, words(USER, payload))
        if kept:
            yield kept


def answers(record, cwd, conversation):
    """Each question the owner answered on an `ask_question` card, dated when they answered it:
    its step's metadata 8, a Timestamp.  agy 1.5.2 keeps the card as answered in its payload's
    147 -> 2 -> 22, each question a 1 there holding its words (1), each choice (2: its id 1, its
    label 2), the id of the one picked (4) and the words written in (5).  A question with
    neither, as Esc leaves one, answers nothing."""
    for _kind, metadata, payload in steps(conversation, CARD) or ():
        at = timestamp(field(metadata, 8))
        if at is None:
            continue
        for asked in fields(field(field(field(payload, 147), 2), 22), 1):
            choices = [(field(choice, 1), decoded(field(choice, 2))) for choice in fields(asked, 2)]
            picked = field(asked, 4)
            given = [label for named, label in choices if picked is not None and named == picked]
            given = "\n".join(filter(None, [*given, decoded(field(asked, 5))]))
            if given:
                yield {"at": at, "question": decoded(field(asked, 1)), "answer": given,
                       "choices": [{"label": label, "description": ""} for _, label in choices]}


def timestamp(stamp):
    """A Timestamp's seconds (field 1) and nanoseconds (2, omitted when 0) as seconds, or None
    where it does not read whole: a cut-off field is no date."""
    read, at = {}, 0
    try:
        while at < len(stamp):
            key, at = varint(stamp, at)
            if key not in (1 << 3, 2 << 3) or key in read:
                return None
            read[key], at = varint(stamp, at)
    except (IndexError, TypeError):
        return None
    seconds, nanos = read.get(1 << 3), read.get(2 << 3, 0)
    return None if seconds is None or nanos >= 1_000_000_000 else seconds + nanos / 1e9


def _full_id(model, effort):
    """The full id `adapters/antigravity.sh interactive` hands `--model` and `--settings`."""
    if not effort or effort == "none" or model.endswith(f"-{effort}"):
        return model
    return f"{model}-{effort}"


def same_model(entry, model, effort):
    """Whether `entry` launches on the same full agy id as `(model, effort)`: e.g. a
    configured `gemini-3.1-pro-high` at `high`, or `acme-wide` at `xhigh`, matches what
    agy reports for that launch without adding a duplicate entry."""
    own, own_effort = entry.get("model"), entry.get("effort")
    return (isinstance(own, str) and isinstance(model, str) and isinstance(effort, str)
            and bool(effort) and (own_effort is None or isinstance(own_effort, str))
            and _full_id(own, own_effort) == _full_id(model, effort))


def _fold(model):
    """A full agy model id (`<model>-<effort>`, or bare for no effort) as `(model, effort)`:
    the id itself where the harness lists it at no effort, else split on its trailing effort
    word (any effort the harness or that model lists) as `adapters/antigravity.sh`'s `models`
    folds `agy models`."""
    for table in (config.catalog_held("antigravity"), config.catalog_table("antigravity")):
        said = next((entry["efforts"] for entry in table
                     if entry["id"] == model and entry["efforts"]), None)
        if said:
            if said == ["none"]:
                return model, "none"
            break
    bare, _, effort = model.rpartition("-")
    if bare and effort != "none" and (
            effort in config.efforts("antigravity")
            or effort in config.efforts("antigravity", bare, config.catalog_held)):
        return bare, effort
    return model, "none"


def _resolve_label(record, said):
    """The model id for a resolved status-line label, else the label stripped of its bracketed
    effort.  The seat's own login's exact raw label wins first (preserving live renames a
    manifest label would shadow and bracketed no-effort labels like `Claude Sonnet 4.6
    (Thinking)`), then the shipped `[catalog]` table, then other configured logins' exact raw
    labels, then normalized held labels -- so neither another login nor a normalized live row
    can redirect the seat's own or shipped model."""
    label = re.sub(r" \([^()]*\)$", "", said)
    candidates = (said, label) if label != said else (label,)
    try:
        cfg = config.load() if (config.HOME / config.CONFIG_NAME).is_file() else None
    except (config.Error, OSError):
        cfg = None
    own = record.get("account") if isinstance(record, dict) else None
    groups = config.catalog_held_by_login("antigravity", cfg, own)
    own_rows, other_groups = (groups[0], groups[1:]) if groups else ([], [])

    def exact(rows):
        for candidate in candidates:
            match = next((row["id"] for row in rows if row.get("label") == candidate), None)
            if match is not None:
                return match
        return None

    def normalized(rows, label_of):
        for candidate in candidates:
            named = config.model_label("antigravity", "", candidate)
            match = next((row["id"] for row in rows
                          if config.model_label("antigravity", "", label_of(row)) == named), None)
            if match is not None:
                return match
        return None

    def raw_label(row):
        return row["label"] if isinstance(row.get("label"), str) and row["label"] else row["id"]

    return (exact(own_rows)
            or normalized(config.catalog_table("antigravity"), lambda row: row["label"])
            or next((found for rows in other_groups if (found := exact(rows))), None)
            or next((found for rows in groups if (found := normalized(rows, raw_label))), None)
            or label)


def running(record, cwd, conversation):
    """The newer of that conversation's last answer and its status-line report."""
    from . import model_report
    latest, report = answered_model(conversation), model_report(conversation)
    if report and (not latest or report[2] > latest[2]):
        said, effort, at = report
        # Before `--model` resolves, agy's status line echoes `--settings`'s `model` id
        # verbatim with no effort; once resolved, it reports its own label with a bracketed
        # effort, even as `model.id`.
        if not re.search(r"\s", said):
            model, folded = _fold(said)
            if not effort or model != said:
                return model, effort or folded, at
        return _resolve_label(record, said), effort, at
    return latest


def answered_model(conversation):
    """The model and effort of the generation that made that conversation's latest answer,
    with that answer's time.  agy keeps one `gen_metadata` row per generation, its execution
    beside it (4), and only the newest names the model (3 -> 28), by the id it was launched
    with: `<model>-<effort>`, a model at no effort bare.  An answer step's execution is its
    metadata's 12, so a newest generation of another execution, a failed one's, ties none;
    its 8 the moment the answer was done (every finished one read on 30 Oct 2026, 1.4.11)."""
    from . import rows
    found = store(conversation)
    found = found and rows(found, "SELECT (SELECT metadata FROM steps WHERE step_type = ?"
                                  " ORDER BY idx DESC LIMIT 1),"
                                  " (SELECT data FROM gen_metadata ORDER BY idx DESC LIMIT 1)",
                           MODEL)
    if not found:
        return None
    (metadata, generation), = found
    execution, model = field(generation, 4), field(field(generation, 3), 28)
    at = timestamp(field(metadata, 8))
    if not execution or execution != field(metadata, 12) or not model or at is None:
        return None
    return (*_fold(model.decode(errors="replace")), at)


def steps(conversation, *kinds):
    """(step_type, metadata, step_payload) of each of that conversation's steps of those kinds,
    in order, or None where it has no store to read."""
    from . import rows
    found = store(conversation)
    return found and rows(found, "SELECT step_type, metadata, step_payload FROM steps"
                          f" WHERE step_type IN ({', '.join('?' * len(kinds))}) ORDER BY idx",
                          *kinds)


def store(conversation):
    """That conversation's database, or None for an id that names no file of its own."""
    if not isinstance(conversation, str) or not re.fullmatch(r"[\w-]+", conversation):
        return None
    return conversation_stores()[0]["root"] / f"{conversation}.db"


def words(kind, payload):
    """The words a step of that kind keeps in its payload, or ''."""
    _who, step, text = WORDS[kind]
    return (field(field(payload, step), text) or b"").decode(errors="replace")


def conversation_stores():
    """The default home's conversations: agy 1.4.4 ends none, and only an RPC no subcommand
    reaches (DeleteConversation) would."""
    return [{"root": Path.home() / ".gemini/antigravity-cli/conversations", "pattern": "*.db",
             "id": re.compile(r"(.+)\.db")}]


def end_conversation(path, ends):
    """Its row in every home's conversation_summaries.db, its annotations, implicit and presence
    files in every home, its brain folder, then its .db: a pass cut short finds the .db again.
    Asked once every home's summaries wait on us, as agy writes a conversation's summary there."""
    conversation = Path(path)
    default = conversation.parents[1]
    homes = [default, *sorted(default.parent.glob(f"{default.name}-*"))]
    parts = [home / name / f"{conversation.stem}{suffix}" for home in homes
             for name, suffix in (("annotations", ".pbtxt"), ("implicit", ".pb"),
                                  ("presence", ".lock"))]
    parts.append(default / "brain" / conversation.stem)
    from .. import retention   # here: retention imports this package
    try:
        with contextlib.ExitStack() as held:
            summaries = []
            for found in (home / "conversation_summaries.db" for home in homes):
                if not there(found):
                    continue
                if not retention.safe(found):
                    raise OSError(f"{found} is reached through a link or is not a file of ours")
                db = held.enter_context(contextlib.closing(sqlite3.connect(
                    found.as_uri() + "?mode=rw", uri=True, timeout=30)))
                held.enter_context(db)
                db.execute("BEGIN IMMEDIATE")
                summaries.append(db)
            parts = [part for part in parts if there(part)]
            if not ends(*parts):
                return
            for db in summaries:
                db.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?",
                           (conversation.stem,))
    except sqlite3.Error as exc:
        raise OSError(f"Antigravity's conversation summaries: {exc}") from exc
    for part in parts:     # ends refused any reached through a link
        if part.is_dir():
            shutil.rmtree(part)
        else:
            part.unlink()
    conversation.unlink()


def there(path):
    """Whether something is at that path, link or not; what cannot be looked at raises, as a
    home nobody may search may still keep a row or a file of the conversation."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def field(message, number, wire=2):
    """That field of a protocol buffer message, its first, or None: a length-delimited one (wire
    type 2) as bytes, a varint (VARINT) as its number."""
    return next(fields(message, number, wire), None)


def fields(message, number, wire=2):
    """Each field of that number and wire type in a protocol buffer message, in order, up to
    where it no longer reads: a length-delimited one as bytes, a varint as its number."""
    at = 0
    try:
        while isinstance(message, bytes) and at < len(message):
            key, at = varint(message, at)
            if key & 7 == 2:
                size, at = varint(message, at)
                if key == number << 3 | wire and at + size <= len(message):
                    yield message[at:at + size]
                at += size
            elif key & 7 == 0:
                value, at = varint(message, at)
                if key == number << 3 | wire:
                    yield value
            elif key & 7 in (1, 5):
                at += 8 if key & 7 == 1 else 4
            else:
                return
    except IndexError:
        return


def decoded(data):
    """A field's bytes as text, or None where there is no field."""
    return None if data is None else data.decode(errors="replace")


def varint(message, at):
    """The variable-length integer starting at `at`, and where the next field starts."""
    value = shift = 0
    while True:
        byte = message[at]
        value, at, shift = value | (byte & 0x7F) << shift, at + 1, shift + 7
        if byte < 0x80:
            return value, at

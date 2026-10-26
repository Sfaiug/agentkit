"""Antigravity: the conversation a seat holds, read back for a model taking the seat over, and
ended, with what every home keeps of it, once `ak gc` finds it stale.

agy's TUI cannot be handed an id for a new conversation, so a seat's is learned rather than
issued: each launch carries a token of its own in its environment, and the conversation a
process carrying it holds open is that launch's (agy 1.4.7 makes `<id>.db` within seconds and
holds it, its -wal and -shm open while it runs).  A host whose processes' open files cannot be
read gives a seat none, as before.

agy keeps each conversation as a SQLite database of its own, ~/.gemini/antigravity-cli/
conversations/<id>.db, where every login's are (adapters/antigravity.sh links them): one row
per step, its `step_payload` a protocol buffer.  agy ships no schema for it; the numbers below
were read off agy 1.2.13's own databases.
"""

import contextlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .. import config
from . import LAUNCHER, issued

# `steps.step_type`, and where each keeps its words in its payload: a user input's text, and
# a planner response's answer -- its thinking (3) and tool calls (7) are fields beside that.
USER, MODEL = 14, 15
WORDS = {USER: ("user", 19, 2), MODEL: ("model", 20, 1)}
LAUNCH_ENV = "AGENTKIT_ANTIGRAVITY_LAUNCH"
PROC = Path("/proc")


def launched(name, cwd, conversation):
    """A resumed conversation is the launcher's id; a new one is learned under this token."""
    token = uuid.uuid4().hex
    issued(name, conversation, antigravity_launch=token, antigravity_open=None)
    return {LAUNCH_ENV: token}


def conversation(record, cwd=None):
    """The conversation the record gives this seat, else the one its launch's own agy holds
    open, written down beside that launch's token so it outlives the process and a stale
    launch's is never a later one's.  One another seat owns is never this one's, nor a guess
    between two."""
    mine, token = owned(record), record.get("antigravity_launch")
    if mine or not isinstance(token, str):
        return mine
    records = config.session_records()
    name = next((name for name, kept in records.items()
                 if kept.get("antigravity_launch") == token), None)
    held = held_open(token) - {owned(kept) for other, kept in records.items() if other != name}
    if name is None or len(held) != 1:
        return None
    found = held.pop()
    config.update_session(name, antigravity_open={"launch": token, "conversation": found})
    return found


def owned(record):
    """What that record alone says its seat owns: a launcher's id, or one its launch saw."""
    if record.get("id_source") == LAUNCHER:
        return record.get("conversation")
    seen = record.get("antigravity_open")
    if isinstance(seen, dict) and seen.get("launch") == record.get("antigravity_launch"):
        return seen.get("conversation")
    return None


def resumable(record, cwd, conversation):
    return bool(conversation)


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


def steps(conversation, *kinds):
    """(step_type, metadata, step_payload) of each of that conversation's steps of those kinds,
    in order, or None where it has no store to read."""
    from . import rows
    if not isinstance(conversation, str) or not re.fullmatch(r"[\w-]+", conversation):
        return None
    return rows(conversation_stores()[0]["root"] / f"{conversation}.db",
                "SELECT step_type, metadata, step_payload FROM steps"
                f" WHERE step_type IN ({', '.join('?' * len(kinds))}) ORDER BY idx", *kinds)


def words(kind, payload):
    """The words a step of that kind keeps in its payload, or ''."""
    _who, step, text = WORDS[kind]
    return (field(field(payload, step), text) or b"").decode(errors="replace")


def conversation_stores():
    """The default home's conversations: agy 1.4.4 ends none, and only an RPC no subcommand
    reaches (DeleteConversation) would."""
    return [{"root": Path.home() / ".gemini/antigravity-cli/conversations", "pattern": "*.db"}]


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


def field(message, number):
    """That length-delimited field of a protocol buffer message, as bytes, or None."""
    at = 0
    try:
        while isinstance(message, bytes) and at < len(message):
            key, at = varint(message, at)
            if key & 7 == 2:
                size, at = varint(message, at)
                if key >> 3 == number and at + size <= len(message):
                    return message[at:at + size]
                at += size
            elif key & 7 == 0:
                at = varint(message, at)[1]
            elif key & 7 in (1, 5):
                at += 8 if key & 7 == 1 else 4
            else:
                return None
    except IndexError:
        return None


def varint(message, at):
    """The variable-length integer starting at `at`, and where the next field starts."""
    value = shift = 0
    while True:
        byte = message[at]
        value, at, shift = value | (byte & 0x7F) << shift, at + 1, shift + 7
        if byte < 0x80:
            return value, at

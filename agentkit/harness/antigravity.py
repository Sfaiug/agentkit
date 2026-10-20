"""Antigravity: the conversation a seat holds, read back for a model taking the seat over.

agy keeps each conversation as a SQLite database of its own, ~/.gemini/antigravity-cli/
conversations/<id>.db, where every login's are (adapters/antigravity.sh links them): one row
per step, its `step_payload` a protocol buffer.  agy ships no schema for it; the numbers below
were read off agy 1.2.13's own databases.
"""

from pathlib import Path
import re

# `steps.step_type`, and where each keeps its words in its payload: a user input's text, and
# a planner response's answer -- its thinking (3) and tool calls (7) are fields beside that.
WORDS = {14: ("user", 19, 2), 15: ("model", 20, 1)}


def said(record, cwd, conversation):
    from . import rows
    if not isinstance(conversation, str) or not re.fullmatch(r"[\w-]+", conversation):
        return None
    found = rows(Path.home() / ".gemini/antigravity-cli/conversations" / f"{conversation}.db",
                 "SELECT step_type, step_payload FROM steps WHERE step_type IN (?, ?)"
                 " ORDER BY idx", *WORDS)
    if found is None:
        return None
    said = []
    for kind, payload in found:
        who, step, words = WORDS[kind]
        text = field(field(payload, step), words)
        try:
            text = text.decode() if text else ""
        except UnicodeDecodeError:
            continue
        if text:
            said.append({"who": who, "text": text})
    return said


def field(message, number):
    """The first length-delimited field of that number in a protocol buffer message, as bytes,
    or None where it has none or the message is not one."""
    if not isinstance(message, bytes):
        return None
    at = 0
    try:
        while at < len(message):
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
    return None


def varint(message, at):
    """The variable-length integer starting at `at`, and where the next field starts."""
    value = shift = 0
    while True:
        byte = message[at]
        value, at, shift = value | (byte & 0x7F) << shift, at + 1, shift + 7
        if byte < 0x80:
            return value, at

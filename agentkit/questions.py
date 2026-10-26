"""Whether a recorded question has reached the assistant's visible message.

This hides the difference between questions kept during a turn and notices already standing.
The question records remain notify/watch's; delivery compares their words, never guesses an
intent from prose or counts a tool result as the assistant speaking.
"""

import re


def pending(name):
    from . import notify, watch
    notice = notify.last(name)
    standing = notify.questions(notice) if watch.owner_question(notice) else []
    kept = watch.questions_kept(watch.seat_read(name).get("unasked"))
    return list(dict.fromkeys([*standing, *(q["text"] for q in kept)]))


def words(text):
    # The model may draw the same choices as a Markdown list instead of the recorded inline
    # list. Neither its numbering nor the generated "Options:" label is question content.
    text = re.sub(r"\bOptions:\s*", "\n", (text or "").replace("·", "\n"))
    text = re.sub(r"(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    return " ".join(text.translate(str.maketrans("", "", "*`")).split())


def reminder(name, message):
    missing = [question for question in pending(name) if words(question) not in words(message)]
    if not missing:
        return ""
    return ("Write these unanswered questions and their choices in your closing assistant "
            "message, in the chat. The owner must see them there before you stop. "
            "They are already recorded; do not register them again.\n\n" + "\n\n".join(missing))


def unseen(name, harness, found):
    """`reminder` for a seat with no blocking Stop, its closing message the newest in its
    conversation (`said`) and only if the model's; an unreadable one proves no delivery.  After
    a turn the owner interrupted (`found`) nothing: it rests."""
    from . import notify, watch
    if not watch.stop_enforced(harness) or found.get("interrupted") or not pending(name):
        return ""
    seat = notify.conversation_of(name)
    try:
        said = seat[0].said(*seat[1:]) if seat and seat[3] else None
    except (OSError, ValueError):
        said = None
    last = said[-1] if said else {}
    return reminder(name, last["text"] if last.get("who") == "model" else "")

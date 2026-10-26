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


def listed(text):
    """`text` with each Markdown list written as the recorded inline list, `a, b.`: a choice's
    own punctuation stays its words, as `notify.replied` reads them."""
    lines, items = [], []
    for line in (text or "").splitlines():
        item = re.match(r"\s*(?:[-*+]|\d+[.)])\s+(.*\S)", line)
        if item or not line.strip():
            items += [item[1]] if item else []
            continue
        lines += [", ".join(items) + "."] * bool(items) + [line]
        items = []
    return "\n".join(lines + [", ".join(items) + "."] * bool(items))


def reminder(name, message):
    said = words(message), words(listed(message))
    missing = [question for question in pending(name)
               if not any(words(question) in shown for shown in said)]
    if not missing:
        return ""
    return ("Write these unanswered questions and their choices in your closing assistant "
            "message, in the chat. The owner must see them there before you stop. "
            "They are already recorded; do not register them again.\n\n" + "\n\n".join(missing))


def unseen(name, harness, found):
    """`reminder` for a seat with no blocking Stop, its closing message the newest in its
    conversation (`said`) and only if the model's; an unreadable one proves no delivery.  After
    a turn the owner interrupted (`found`), or for a seat owning no conversation (Antigravity's
    where open files cannot be read), nothing: it rests, as nothing would ever prove it seen."""
    from . import notify, watch
    if not watch.stop_enforced(harness) or found.get("interrupted") or not pending(name):
        return ""
    seat = notify.conversation_of(name)
    if not seat or not seat[3]:
        return ""
    try:
        said = seat[0].said(*seat[1:])
    except (OSError, ValueError):
        said = None
    last = said[-1] if said else {}
    return reminder(name, last["text"] if last.get("who") == "model" else "")

"""Whether a recorded question has reached the assistant's visible message.

This hides the difference between questions kept during a turn and notices already standing.
The question records remain notify/watch's; delivery compares their words, never guesses an
intent from prose or counts a tool result as the assistant speaking.
"""


def pending(name):
    from . import notify, watch
    notice = notify.last(name)
    standing = notify.questions(notice) if watch.owner_question(notice) else []
    kept = watch.questions_kept(watch.seat_read(name).get("unasked"))
    return list(dict.fromkeys([*standing, *(q["text"] for q in kept)]))


def words(text):
    # Markdown emphasis and the separator used between choices do not change the question.
    return " ".join((text or "").translate(str.maketrans("", "", "*`·")).split())


def reminder(name, message):
    missing = [question for question in pending(name) if words(question) not in words(message)]
    if not missing:
        return ""
    return ("Write these unanswered questions and their choices in your closing assistant "
            "message, in the chat. The owner must see them there before you stop. "
            "They are already recorded; do not register them again.\n\n" + "\n\n".join(missing))

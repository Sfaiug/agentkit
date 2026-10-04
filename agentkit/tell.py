"""`ak tell SEAT TEXT`: one seat's message to another, the same way for every harness.

The message waits in the receiving seat's own file until ak types it there, once, at that
seat's next quiet prompt, through the confirmed send a run's ending takes
(`watch.type_at_prompt`): under the seat's typing lock, never onto a draft or a dialog, and
never while the owner's question stands, so it answers none.  ak writes the header that says
who it is from, and the typing receipt names that seat as its source, so the line is never the
owner's words.  The sender tries once and returns; the tick types what still waits.
"""

import json
import os
import sys
import time
import uuid

from . import command_help, config, host, notify, orch, watch

# tmux refuses one command past 16 KiB, and the whole message goes in as one typed line.
MAX_BYTES = 8000


def source(sender):
    """The typing receipt's source for a line one seat sent another."""
    return f"seat:{sender}"


def read(path):
    """The messages waiting there, oldest first; [] for none or an unreadable file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [message for message in data if isinstance(message, dict)
            and isinstance(message.get("id"), str) and isinstance(message.get("from"), str)
            and isinstance(message.get("line"), str)]


def write(path, messages):
    if not messages:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(messages, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def edit(name, change):
    """Rewrite that seat's waiting messages with `change`, returning what it hands back.

    Only while the seat's own lock is held -- the one a rename takes, so the file is the seat's
    under the name it goes by now and no rename moves it meanwhile.  `change` edits the list in
    place.
    """
    path = config.seat_file("tell", config.resolve_session(name))
    messages = read(path)
    answer = change(messages)
    write(path, messages)
    return answer


def locked(name, change):
    """`edit` under that seat's lock."""
    with notify.session_lock(name) as current:
        return edit(current, change)


def me():
    """This process, as a claim another can test for life after it is gone."""
    return {"pid": os.getpid(), "identity": host.process_identity(os.getpid())}


def claimed(claim):
    """Is that claim another live process's: one typing the message now?"""
    if not isinstance(claim, dict) or claim == me():
        return False
    if claim.get("identity"):
        return host.process_identity(claim.get("pid")) == claim["identity"]
    return host.alive(claim.get("pid"))


def deliver_to(session, log, cfg=None):
    """Type the oldest message waiting for that seat; True when one went in.

    The oldest is claimed first, under the seat's lock, so the sender and the tick never type
    it both; a claim whose process has died is taken over.  The line was fixed when it was
    sent, so a retry presses Enter on the very text in the composer: `typed` is the mark the
    receipt left, written under the typing lock the receipt is told under, the seat's own.
    """
    name = session["name"]

    def take(messages):
        if not messages or claimed(messages[0].get("claim")):
            return None
        messages[0]["claim"] = me()
        return dict(messages[0])

    first = locked(name, take)
    if first is None:
        return False

    def mark(field, value):
        def change(messages):
            for message in messages:
                if message["id"] == first["id"]:
                    if value is None:
                        message.pop(field, None)
                    else:
                        message[field] = value
        return change

    def drop(messages):
        messages[:] = [message for message in messages if message["id"] != first["id"]]

    typed = False
    try:
        # the receipt is told under the seat's typing lock, which is this same lock
        typed = watch.type_at_prompt(
            session, first["line"], log, cfg=cfg, typed=first.get("typed"),
            receipt=lambda receipt: edit(name, mark("typed", receipt)),
            source=source(first["from"]))
    finally:
        locked(name, drop if typed else mark("claim", None))
    if typed:
        log(f"{config.resolve_session(name)}: typed a message from {first['from']}")
    return typed


def deliver(cfg, log):
    """The tick's pass: each open seat with messages waiting gets its oldest one."""
    waiting = {seat for seat, _ in config.seat_files("tell")}
    if not waiting:
        return
    for session in orch.sessions():
        if session["name"] in waiting and not any(session.get(key) for key in orch.CLOSED):
            deliver_to(session, log, cfg)


def main(argv):
    if command_help.show("tell", argv):
        return 0
    if len(argv) != 2 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["tell"][0])
    sender = config.current_session()
    if not sender:
        print("ak tell: no seat: run it inside an orchestrator session", file=sys.stderr)
        return 1
    name = config.resolve_session(argv[0])
    if name == sender:
        print(f"ak tell: {sender} is this seat", file=sys.stderr)
        return 1
    if name not in config.session_records():
        print(f"ak tell: no session {argv[0]!r}; `ak orch list` shows them", file=sys.stderr)
        return 1
    if watch.seat_read(name).get("stopped_at"):
        print(f"ak tell: {name} is closed", file=sys.stderr)
        return 1
    text = " ".join(argv[1].split())
    if not text:
        print("ak tell: nothing to say", file=sys.stderr)
        return 1
    now = time.time()
    line = (f"[from seat {sender} at {time.strftime('%H:%M', time.localtime(now))}, not the "
            f"owner; reply with ak tell {sender}] {text}")
    size = len(line.encode("utf-8"))
    if size > MAX_BYTES:
        print(f"ak tell: {size:,} bytes is more than one typed line holds ({MAX_BYTES:,}); "
              "write the rest to a file and tell its path", file=sys.stderr)
        return 1
    message = {"id": uuid.uuid4().hex, "from": sender, "at": now, "line": line}
    locked(name, lambda messages: messages.append(message))
    session = orch.find(config.resolve_session(name))
    if session and not any(session.get(key) for key in orch.CLOSED):
        deliver_to(session, lambda _: None)
    waiting = locked(name, lambda messages: any(entry["id"] == message["id"]
                                                for entry in messages))
    name = config.resolve_session(name)
    if not waiting:
        print(f"{name}: told")
    elif watch.owner_question(notify.last(name)):
        print(f"{name}: waits on the owner's answer; ak types this after it")
    else:
        print(f"{name}: busy; ak types this at its next quiet prompt")
    return 0

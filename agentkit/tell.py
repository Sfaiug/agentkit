"""`ak tell SEAT TEXT`: one seat's message to another, the same way for every harness.

The message waits in the receiving seat's own file until ak types it there, once, at that
seat's next quiet prompt, through the confirmed send a run's ending takes
(`watch.type_at_prompt`): under the seat's typing lock, never onto a draft or a dialog, and
never while the owner's question stands, so it answers none.  ak writes the header that says
who it is from, and the typing receipt names that seat as its source, so the line is never the
owner's words.  The sender tries once and returns; the tick types what still waits.  Whoever
types it may die at any key: the receipt, written before the keys, and the seat's conversation
say afterwards how far it got.
"""

import json
import os
import re
import sys
import time
import uuid

from . import command_help, config, harness, host, notify, orch, watch

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


def seat_of(name):
    """The seat that name is now, as the moment its record was made, or None for no open seat.

    A seat closed and opened again under the same name is another seat: a message meant for
    the first is never the second's.
    """
    record = config.session_records().get(name)
    if record is None or watch.seat_read(name).get("stopped_at"):
        return None
    return record.get("created", "")


def settled(alias):
    """(the name that alias goes by, the seat it is), read in a stretch no rename fell inside.

    Read again where a rename moved the seat meanwhile; the queue asks once more under its lock.
    """
    for _ in range(3):
        name = config.resolve_session(alias)
        seat = seat_of(name)
        if config.resolve_session(alias) == name:
            break
    return name, seat


def typed_in(name, message):
    """The newest receipt of that message typed into that seat, else None.

    `watch` writes it under the seat's typing lock before the keys and takes it back where they
    fail, so it outlives a typer that died at any key after.  It names the message's id: two
    messages can hold the same line.
    """
    found = None
    for sent in harness.entries(config.seat_file("input", name)):
        if sent.get("ref") == message["id"]:
            found = sent
    return found


def reached(name, sent):
    """Did the line that receipt typed reach the seat's conversation?  None where ak cannot read
    one there."""
    record = config.session_records().get(name) or {}
    plugin = orch.seat_plugin(record)
    if not plugin.keeps_messages or not sent.get("conversation"):
        return None
    messages = plugin.user_messages(record, record.get("cwd"), sent["conversation"])
    return any(message["text"] == sent["text"] for message in messages[sent.get("after", 0):])


def in_composer(name, session, line):
    """Does that seat's composer hold the line now -- its keys landed, whatever came after?"""
    plugin = orch.seat_plugin(config.session_records().get(name) or {})
    held = watch.composer_draft(plugin.name, watch.pane_text(session)) or ""
    return re.sub(r"\s+", "", line) in held


def refusal(sender, name, seat=None):
    """Why that sender cannot tell that seat now -- or, given `seat`, no longer -- else None."""
    if name == sender:
        return f"{sender} is this seat"
    now = seat_of(name)
    if now is None:
        return (f"{name} is closed" if name in config.session_records()
                else f"no session {name!r}; `ak orch list` shows them")
    if seat is not None and now != seat:
        return f"{name} was closed and opened again; nothing was sent"
    return None


def deliver_to(session, log, cfg=None):
    """Type the oldest message waiting for that seat; True when one went in.

    The oldest is claimed first, under the seat's lock, so the sender and the tick never type
    it both; a claim whose process has died is taken over.  A line typed before -- by a typer
    that died, or one whose Enter did not send it -- is settled by where it is now: in the
    seat's conversation it went in, in its composer it gets its Enter, and in neither it is
    typed again.  Where ak reads no conversation, the mark its typer left once its keys were in
    stands for it: with that mark an empty composer means it went in, without it the keys never
    landed -- the receipt is written before them -- and it is typed again.
    """
    name = session["name"]

    def take(messages):
        # meant for a seat this name no longer is: never typed into the one it is now
        seat = seat_of(config.resolve_session(name))
        messages[:] = [message for message in messages if message.get("seat", seat) == seat]
        if not messages or claimed(messages[0].get("claim")):
            return None
        messages[0]["claim"] = me()
        return dict(messages[0])

    first = locked(name, take)
    if first is None:
        return False

    def setting(field, value):
        """A change setting that field of the claimed message, or removing it for None."""
        def apply(messages):
            for message in messages:
                if message["id"] == first["id"]:
                    message.pop(field, None)
                    if value is not None:
                        message[field] = value
        return apply

    def drop(messages):
        messages[:] = [message for message in messages if message["id"] != first["id"]]

    def type_it(pending):
        return watch.type_at_prompt(
            session, first["line"], log, cfg=cfg,
            typed=watch.typing_mark(session, first["line"]) if pending else None,
            # told under the typing lock, the seat's own, once the keys are in
            receipt=lambda _mark: edit(name, setting("keyed", True)),
            source=source(first["from"]), ref=first["id"],
            # under the typing lock, right before each key: still the seat it was meant for
            stale=lambda held: "seat" in first and seat_of(held) != first["seat"])

    typed = False
    try:
        with notify.session_lock(name) as current:
            sent = typed_in(current, first)
        went_in = reached(current, sent) if sent else False
        if went_in is None and not first.get("keyed"):
            # no conversation to read, and no mark that its keys landed: the composer says
            if in_composer(current, session, first["line"]):
                locked(name, setting("keyed", True))
            else:
                went_in = False
        typed = went_in or type_it(pending=sent is not None)
        if typed and sent and went_in is False:
            # neither in its conversation nor, as the Enter found, in its composer: typed again
            typed = type_it(pending=False)
    finally:
        locked(name, drop if typed else setting("claim", None))
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
    # the seat it is for is read once, here; every later answer is held to it
    name, seat = settled(argv[0])
    if name == sender:
        refused = f"{sender} is this seat"
    elif seat is None:
        refused = (f"{name} is closed" if name in config.session_records()
                   else f"no session {name!r}; `ak orch list` shows them")
    else:
        refused = None
    if refused:
        print(f"ak tell: {refused}", file=sys.stderr)
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
    message = {"id": uuid.uuid4().hex, "from": sender, "at": now, "line": line, "seat": seat}

    def queue(messages):
        # asked again under the seat's lock, with both names as they are now: a rename or a
        # close that came after the first answer is not past it
        refused = refusal(config.current_session(), config.resolve_session(name), seat)
        if not refused:
            messages.append(message)
        return refused

    refused = locked(name, queue)
    if refused:
        print(f"ak tell: {refused}", file=sys.stderr)
        return 1
    session = orch.find(config.resolve_session(name))
    if session and not any(session.get(key) for key in orch.CLOSED):
        deliver_to(session, lambda _: None)        # the oldest waiting, which may be another
    waiting = locked(name, lambda messages: any(entry["id"] == message["id"]
                                                for entry in messages))
    name = config.resolve_session(name)
    # gone from the queue untyped -- by this call or the tick's -- is a seat replaced meanwhile
    if not waiting and typed_in(name, message):
        print(f"{name}: told")
    elif not waiting:
        print(f"ak tell: {name} was closed and opened again; nothing was sent", file=sys.stderr)
        return 1
    elif watch.owner_question(notify.last(name)):
        print(f"{name}: waits on the owner's answer; ak types this after it")
    else:
        print(f"{name}: busy; ak types this at its next quiet prompt")
    return 0

"""`ak tell SEAT TEXT`: one seat's message to another, the same way for every harness.

The sender only queues it, in the receiving seat's own file, under that seat's lock.  The tick
types it there, once, at the seat's next quiet prompt, through the confirmed send a run's ending
takes (`watch.type_at_prompt`): under the seat's typing lock, never onto a draft or a dialog,
and never while the owner's question stands, so it answers none.  ak writes the header that
says who it is from, and the typing receipt names that seat as its source, so the line is never
the owner's words.  Only the tick types, one tick at a time; one that dies at any key leaves
the message's own mark, made once its keys are in and before its Enter, and the seat's
composer to say how far it got.
"""

import json
import re
import sys
import time
import uuid

from . import command_help, config, notify, orch, watch

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


def seat_of(name):
    """The seat that name is now, as the moment its record was made, or None for no open seat.

    A seat closed and opened again under the same name is another seat: a message meant for
    the first is never the second's.
    """
    record = config.session_records().get(name)
    if record is None or watch.seat_read(name).get("stopped_at"):
        return None
    return record.get("created", "")


def composed(name, session):
    """What that seat's composer holds now, whole and without whitespace; None for none read."""
    plugin = orch.seat_plugin(config.session_records().get(config.resolve_session(name)) or {})
    return watch.composer_draft(plugin.name, watch.pane_text(session))


def refusal(name, seat):
    """Why nothing can be queued for that seat, asked under its lock, else None."""
    if name == config.current_session():
        return f"{name} is this seat"
    if name not in config.session_records():
        return f"no session {name!r}; `ak orch list` shows them"
    if seat is None:
        return f"{name} is closed"
    return None


def deliver_to(session, log, cfg=None):
    """Type the oldest message waiting for that seat; True when one went in.

    Only the tick calls this, and one tick runs at a time, so nothing else types it meanwhile.
    A line a tick died on is settled by its mark, made under the seat's lock once its keys are
    in and before its Enter, and by the seat's composer, read whole: keyed and the line alone
    in the composer, it gets its Enter; keyed and the composer empty, it went in; keyed and
    anything else there, the owner's edit too, it waits.  Not keyed, its keys may still have
    landed right before the tick died: the line alone in the composer is marked and gets its
    Enter; an empty composer means it never went in, and it is typed afresh; anything else
    there, or no composer read, is never typed onto.
    """
    name = session["name"]

    def take(messages):
        # meant for a seat this name no longer is: never typed into the one it is now
        seat = seat_of(config.resolve_session(name))
        messages[:] = [message for message in messages if message.get("seat") == seat]
        return dict(messages[0]) if messages else None

    first = locked(name, take)
    if first is None:
        return False

    def keyed(messages):
        for message in messages:
            if message["id"] == first["id"]:
                message["keyed"] = True

    def drop(messages):
        messages[:] = [message for message in messages if message["id"] != first["id"]]

    def type_it(pending):
        return watch.type_at_prompt(
            session, first["line"], log, cfg=cfg,
            typed=watch.typing_mark(session, first["line"]) if pending else None,
            # told under the typing lock, the seat's own, once the keys are in
            receipt=lambda _mark: edit(name, keyed),
            source=source(first["from"]),
            # under the typing lock, right before each key: still the seat it was meant for
            stale=lambda held: seat_of(held) != first["seat"])

    if not first.get("keyed"):
        held = composed(name, session)
        if held == re.sub(r"\s+", "", first["line"]):
            locked(name, keyed)
            first["keyed"] = True
        elif held != "":
            return False
    typed = type_it(pending=bool(first.get("keyed")))
    if typed:
        locked(name, drop)
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
    # Under the receiver's lock, the one a rename and a close take: the seat it is now is the
    # one the message is for, and only that seat's tick pass types it.
    with notify.session_lock(argv[0]) as name:
        seat = seat_of(name)
        refused = refusal(name, seat)
        if not refused:
            edit(name, lambda messages: messages.append(
                {"id": uuid.uuid4().hex, "from": sender, "at": now, "line": line, "seat": seat}))
    if refused:
        print(f"ak tell: {refused}", file=sys.stderr)
        return 1
    after = ("after the owner answers its question" if watch.owner_question(notify.last(name))
             else "at its next quiet prompt")
    print(f"{name}: queued; ak types it {after}")
    return 0

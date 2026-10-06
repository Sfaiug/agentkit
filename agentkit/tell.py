"""`ak tell SEAT TEXT`: one seat's message to another, the same way for every harness.

The sender only queues it, in the receiving seat's own file, under that seat's lock.  The tick
types it there, once, at the seat's next quiet prompt -- or mid-turn, where its harness holds a
typed line for its model's next step -- through the confirmed send a run's ending takes
(`watch.type_at_prompt`): under the seat's typing lock, never onto a draft or a dialog,
and never while the owner's question stands, so it answers none.  ak writes the header that
says who it is from, and the typing receipt names that seat as its source, so the line is never
the owner's words.  Only the tick types, one tick at a time, and a message leaves the queue
only once its line was seen leaving the composer: it goes in at least once and is never lost.
"""

import json
import re
import sys
import time
import uuid

from . import command_help, config, notify, orch, watch

# tmux refuses one command past 16 KiB, and the whole message goes in as one typed line.
MAX_BYTES = 8000


def longest(cfg):
    """The most characters a told line may hold: one every harness a seat can run shows whole
    in its composer (`[screen] folds_over`), so the line read back there is the line typed."""
    harnesses = {model.get("harness") for model in (cfg.get("models") or {}).values()}
    folds = [watch.screen(name)["folds_over"] for name in harnesses if name]
    return min([fold for fold in folds if fold] or [MAX_BYTES])


def too_long(line):
    """Why `line` is more than a told line may hold, else None."""
    most = longest(config.load())
    if len(line) > most or len(line.encode("utf-8")) > MAX_BYTES:
        return (f"{len(line):,} characters is more than a composer shows whole ({most:,}); "
                "write the rest to a file and tell its path")
    return None


def source(sender):
    """The typing receipt's source for a line one seat sent another; no seat is ak itself."""
    return f"seat:{sender}" if sender else "ak"


def read(path):
    """The messages waiting there, oldest first; [] where there is no file.

    A file that cannot be read or is not the queue `write` writes raises -- OSError or
    ValueError -- so nothing rewrites it from a list it never held: its messages stay.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    data = json.loads(text)
    if not (isinstance(data, list) and all(
            isinstance(message, dict) and all(isinstance(message.get(key), str)
                                              for key in ("id", "from", "line"))
            for message in data)):
        raise ValueError(f"{path} is not a message queue")
    return data


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


def composer_holds(name, session, line):
    """What that seat's composer holds now, off one capture: "line" (that line alone), "empty",
    or "other" -- anything else, no composer read, or a question to the owner on the screen,
    as a dialog that keeps the composer drawn is."""
    name = config.resolve_session(name)
    harness = orch.seat_plugin(config.session_records().get(name) or {}).name
    pane = watch.pane_text(session)
    held = watch.composer_draft(harness, pane)
    if held is None or watch.asking(name, harness, pane):
        return "other"
    if held == "":
        return "empty"
    return "line" if held == re.sub(r"\s+", "", line) else "other"


def refusal(name, seat, sender):
    """Why nothing can be queued for that seat from `sender` (none is ak itself), asked under its
    lock, else None."""
    if sender and name == config.resolve_session(sender):
        return f"{name} is this seat"
    if name not in config.session_records():
        return f"no session {name!r}; `ak orch list` shows them"
    if seat is None:
        return f"{name} is closed"
    return None


def queue(name, line, sender=""):
    """Queue `line` for that seat, under its lock, so the tick types it there; None once it is
    queued, else why nothing was.  `sender` is the seat it is from; none is ak itself.

    Under the receiver's lock, the one a rename and a close take: the seat it is now is the
    one the message is for, and only that seat's tick pass types it.
    """
    refused = too_long(line)
    if refused:
        return refused
    with notify.session_lock(name) as name:
        seat = seat_of(name)
        refused = refusal(name, seat, sender)
        if refused:
            return refused
        try:
            edit(name, lambda messages: messages.append(
                {"id": uuid.uuid4().hex, "from": sender, "at": time.time(), "line": line,
                 "seat": seat}))
        except (OSError, ValueError) as exc:
            return f"{name}'s message queue cannot be read, so nothing was queued: {exc}"
    return None


def withdraw(name, line):
    """Take back every copy of `line` still waiting for that seat, under its lock; None once
    none waits, else why one may."""
    def drop(messages):
        messages[:] = [message for message in messages if message["line"] != line]

    try:
        locked(name, drop)
    except (OSError, ValueError) as exc:
        return f"{name}'s message queue cannot be read: {exc}"
    return None


def deliver_to(session, log, cfg=None):
    """Type the oldest message waiting for that seat; True once its line went in.

    Only the tick calls this, and one tick runs at a time, so nothing else types it meanwhile.
    The message leaves the queue only once its composer is read empty right after, with no
    question up, so none is lost; a tick that dies between that and the queue's rewrite, or a
    read that says nothing, leaves it to be typed again.  A
    line a tick died on is settled by the composer, read whole: the line alone there gets its
    Enter, an empty composer is typed into, and anything else there -- the owner's text above
    all, or no composer read -- is never typed onto.
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

    def stale(held):
        # under the typing lock, right before each key: still the seat it was meant for
        return seat_of(held) != first["seat"]

    def ready(current):
        # under the typing lock, right before each Enter: the composer holds this line alone,
        # never an edit the owner made meanwhile, and no question to the owner is up
        return composer_holds(current, session, first["line"]) == "line"

    held = composer_holds(name, session, first["line"])
    if held == "line":
        # typed by a tick that died before its Enter: only the Enter, and its confirmation
        typed = watch.type_checked(
            session, first["line"], log, pending=True, source=source(first["from"]),
            guard=lambda: watch.seat_held(session["name"]), ready=ready,
            veto=lambda current: watch.owner_question(notify.last(current)) or stale(current))
    elif held == "empty":
        typed = watch.type_at_prompt(session, first["line"], log, cfg=cfg, ready=ready,
                                     source=source(first["from"]), stale=stale, midturn=True)
    else:
        return False

    def drop(messages):
        messages[:] = [message for message in messages if message["id"] != first["id"]]

    # leaves the queue only on positive evidence: its composer read empty right after, with no
    # question up -- never on a capture that failed or a dialog that came up over the line
    if not typed or composer_holds(name, session, first["line"]) != "empty":
        return False
    locked(name, drop)
    log(f"{config.resolve_session(name)}: typed a message from {first['from']}")
    return True


def deliver(cfg, log):
    """The tick's pass: each open seat with messages waiting gets its oldest one."""
    waiting = {seat for seat, _ in config.seat_files("tell")}
    if not waiting:
        return
    for session in orch.sessions():
        if session["name"] in waiting and not any(session.get(key) for key in orch.CLOSED):
            try:
                deliver_to(session, log, cfg)
            except (OSError, ValueError) as exc:
                log(f"WARN {session['name']}: its messages wait, their queue unread: {exc}")


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
    refused = queue(argv[0], line, sender)
    if refused:
        print(f"ak tell: {refused}", file=sys.stderr)
        return 1
    name = config.resolve_session(argv[0])
    after = ("after the owner answers its question" if watch.owner_question(notify.last(name))
             else "as soon as it can take a line")
    print(f"{name}: queued; ak types it {after}")
    return 0

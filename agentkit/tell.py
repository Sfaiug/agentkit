"""`ak tell SEAT TEXT`: one seat's message to another, the same way for every harness.

The message waits in the receiving seat's own file until ak types it there, once, at that
seat's next quiet prompt, through the confirmed send a run's ending takes
(`watch.type_at_prompt`): under the seat's typing lock, never onto a draft or a dialog, and
never while the owner's question stands.  ak writes the header that says who it is from, and
the typing receipt names that seat as its source, so the line is never the owner's words,
answers no question of theirs, and opens a turn the stop hook treats as a peer's.  The sender
tries once and returns; the tick types what still waits.
"""

from contextlib import contextmanager
import fcntl
import json
import sys
import time

from . import command_help, config, notify, orch, watch

# tmux refuses one command past 16 KiB, and the whole message goes in as one typed line.
MAX_BYTES = 8000


def source(sender):
    """The typing receipt's source for a line one seat sent another."""
    return f"seat:{sender}"


@contextmanager
def held(name):
    """That seat's waiting messages, for one reader or writer at a time: sender or tick."""
    path = config.seat_file("tell", name)
    config.ensure_dirs()
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def read(path):
    """The messages waiting there, oldest first; [] for none or an unreadable file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [message for message in data if isinstance(message, dict)
            and isinstance(message.get("from"), str) and isinstance(message.get("line"), str)]


def write(path, messages):
    if not messages:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(messages, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def deliver_to(session, log, cfg=None):
    """Type the oldest message waiting for that seat; True when one went in.

    The line is fixed when it is sent, so a retry presses Enter on the very text in the
    composer: `typed` is the mark the receipt left there, the way a hand-back keeps its own.
    """
    name = session["name"]
    with held(name) as path:
        messages = read(path)
        if not messages:
            return False
        first = messages[0]

        def receipt(mark):
            first["typed"] = mark
            write(path, messages)

        if not watch.type_at_prompt(session, first["line"], log, cfg=cfg, typed=first.get("typed"),
                                    receipt=receipt, source=source(first["from"])):
            return False
        write(path, messages[1:])
    log(f"{name}: typed a message from {first['from']}")
    return True


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
    message = {"from": sender, "at": now, "line": line}
    with held(name) as path:
        write(path, read(path) + [message])
    session = orch.find(name)
    if session and not any(session.get(key) for key in orch.CLOSED):
        deliver_to(session, lambda _: None)
    with held(name) as path:
        waiting = any(entry.get("at") == now and entry.get("from") == sender
                      for entry in read(path))
    if not waiting:
        print(f"{name}: told")
    elif watch.owner_question(notify.last(name)):
        print(f"{name}: waits on the owner's answer; ak types this after it")
    else:
        print(f"{name}: busy; ak types this at its next quiet prompt")
    return 0

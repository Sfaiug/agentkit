"""A feature switch on for everyone for two weeks is proven, and comes out of the code.

A production project names its switches with one command, `features:` in its AGENTS.md. A row
its `list` prints with `everyone` on and `everyone_since` (when it last went on for everyone,
ISO 8601 UTC) at least PROVEN ago is due. Once every EVERY the tick reads each list once,
however many checkouts under ~/code declare its command, and hands the longest-due switch to
the newest open seat filed under one of them, through the queue `ak tell` fills, in a line that
names the project, so it holds wherever it lands. One switch is in hand at a time: it stays in
hand until it has left the list, which the project's own deploy does when the code no longer
reads it, and while it is still listed AGAIN after it was handed, the same line is handed
again. A switch handed and then turned off stays in hand too: the owner's rule (5 Oct 2026) is
that a proven switch comes out, and turning one off later is a code change. With no open seat
there, nothing is handed and the next read tries again. A switch is recorded in hand before
its line is queued, and a record that cannot be read or written stops the pass, so no second
switch is ever handed over one the record does not hold.
"""

from datetime import datetime, timezone
import json
import time

from . import config, orch, tell

PROVEN = 14 * 86400    # the owner's two weeks: on for everyone this long, a switch is proven
EVERY = 3600           # how often the lists are read for this
AGAIN = 86400          # a handed switch still listed this long after is handed again


def path():
    return config.STATE / "retire.json"


def read():
    """The pass's record, {} before its first; one that cannot be read raises."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path()} is not the switch retirement record")
    return data


def write(data):
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path())


def since(row):
    """When that row last went on for everyone, in epoch seconds, or None while it is not; a
    stamp with no offset is UTC."""
    stamp = row.get("everyone_since")
    if row.get("everyone") is not True or not isinstance(stamp, str):
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()


def due(rows, now):
    """The rows proven by `now`, longest on for everyone first."""
    stamped = [(since(row), row["id"], row) for row in rows
               if isinstance(row, dict) and isinstance(row.get("id"), str)]
    return [row for at, _, row in sorted(item for item in stamped if item[0] is not None)
            if now - at >= PROVEN]


def line(project, row):
    day = time.strftime("%-d %b", time.localtime(since(row)))
    return (f"[from ak, not the owner] In {project}, the `{row['id']}` switch has been on for "
            f"everyone since {day}: two weeks or more, so it is proven. Take it out of {project}'s "
            "code, so everyone keeps the feature for good. Once the deploy drops it from the "
            "switch list, ak hands over the next.")


def lists():
    """{a `features:` command: the checkouts under ~/code that declare it}. The command is the
    switch list: every checkout of a project declares the same one, and it prints the project's
    live switches wherever it runs, so it keys the list however checkouts come and go; a
    project that changes its command starts a new list."""
    from . import menu   # here, not at the top: the menu is the whole screen
    found = {}
    for checkout in orch.checkouts():
        command = menu.switches_command(checkout)
        if command:
            found.setdefault(command, []).append(checkout)
    return found


def seat_for(checkouts):
    """The newest open seat filed under one of those checkouts, or None."""
    records = config.session_records()
    seats = [session for session in orch.sessions()
             if not any(session.get(key) for key in orch.CLOSED)
             and orch.checkout_of((records.get(session["name"]) or {}).get("repo")) in checkouts]
    return max(seats, key=lambda session: (session.get("created") or 0, session["name"]),
               default=None)


def hand(log, now=None):
    """The tick's pass: per project, the one proven switch in hand, handed to a seat there."""
    from . import menu   # here, not at the top: the menu is the whole screen
    now = time.time() if now is None else now
    record = read()
    if now - record.get("asked", 0) < EVERY:
        return
    record["asked"] = now
    for command, checkouts in lists().items():
        home = checkouts[0]
        entry = record.setdefault(command, {})
        rows, why = menu.features_run(home, "list")
        if not isinstance(rows, list):
            log(f"WARN {home.name}: its switches are unread, so none was handed ({why or 'no list'})")
            continue
        handed = entry.get("handed")
        if handed and not any(isinstance(row, dict) and row.get("id") == handed["id"]
                              for row in rows):
            entry.pop("handed")    # out of the code: the deploy dropped it
            handed = None
        if handed:
            if now - handed["at"] < AGAIN:
                continue
            feature, text = handed["id"], handed["line"]
        else:
            proven = due(rows, now)
            if not proven:
                continue
            feature, text = proven[0]["id"], line(home.name, proven[0])
        seat = seat_for(checkouts)
        if seat is None:
            log(f"{home.name}: switch {feature} is proven; no open seat to hand it to")
            continue
        # in hand before its line is queued: a record that cannot be saved hands nothing
        entry["handed"] = {"id": feature, "at": now, "seat": seat["name"], "line": text}
        write(record)
        refused = tell.queue(seat["name"], text)
        if refused:
            if handed:
                entry["handed"] = handed
            else:
                entry.pop("handed")
            log(f"WARN {home.name}: switch {feature} was not handed: {refused}")
        else:
            log(f"{home.name}: switch {feature} is proven; handed to {seat['name']}")
    write(record)

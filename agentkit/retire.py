"""A feature switch on for everyone for two weeks is proven, and comes out of the code.

A production project names its switches with one command, `features:` in its AGENTS.md. A row
its `list` prints with `everyone` on and `everyone_since` (when it last went on for everyone,
ISO 8601 UTC) at least PROVEN ago is due. A project is a checkout under ~/code, as everywhere
in ak: once every EVERY the tick reads the list of each one that declares a command, and hands
its longest-due switch to the newest open seat filed under that checkout, through the queue
`ak tell` fills, in a line that names the project, so it holds wherever it lands. One switch is
in hand per checkout at a time: it stays in hand until it has left the list, which the project's
own deploy does when the code no longer reads it, and while it is still listed AGAIN after it
was handed, the same line is handed again. A switch handed and then turned off stays in hand
too: the owner's rule (5 Oct 2026) is that a proven switch comes out, and turning one off later
is a code change. One of that id listed as on for everyone since another moment is another
switch, unproven until its own two weeks are up. With no open seat there, nothing is handed and
the next read tries again. A switch is recorded in hand before its line is queued, and a record
that cannot be read or written stops the pass.

Nothing here guesses which checkouts are one project: a guess that merges two hands one
project's work to the other's seat and never reads the other's list. So one project checked
out twice, with open seats filed under both, hears of a switch in each, and a checkout renamed
starts its record afresh; one replaced at the same path keeps the switch in hand only while
its list still shows that switch, on since the same moment, or off.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
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
    """The hand-off for that switch; one longer than a told line may hold is written to a file
    the line names instead, as `ak tell` asks of a longer line."""
    day = time.strftime("%-d %b", time.localtime(since(row)))
    text = (f"[from ak, not the owner] In {project}, the `{row['id']}` switch has been on for "
            f"everyone since {day}: two weeks or more, so it is proven. Take it out of {project}'s "
            "code, so everyone keeps the feature for good. Once the deploy drops it from the "
            "switch list, ak hands over the next.")
    if not tell.too_long(text):
        return text
    whole = config.STATE / "retire" / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.txt"
    whole.parent.mkdir(parents=True, exist_ok=True)
    whole.write_text(text + "\n", encoding="utf-8")
    try:
        shown = f"~/{whole.relative_to(Path.home())}"   # as long however deep the home is
    except ValueError:
        shown = whole
    return (f"[from ak, not the owner] A proven feature switch is yours to take out of the code: "
            f"{shown} says which, and where.")


def seat_for(checkout):
    """The newest open seat filed under that checkout, or None."""
    records = config.session_records()
    seats = [session for session in orch.sessions()
             if not any(session.get(key) for key in orch.CLOSED)
             and orch.checkout_of((records.get(session["name"]) or {}).get("repo")) == checkout]
    return max(seats, key=lambda session: (session.get("created") or 0, session["name"]),
               default=None)


def hand(log, now=None):
    """The tick's pass: per checkout, the one proven switch in hand, handed to a seat there."""
    from . import menu   # here, not at the top: the menu is the whole screen
    now = time.time() if now is None else now
    record = read()
    if now - record.get("asked", 0) < EVERY:
        return
    record["asked"] = now
    for checkout in orch.checkouts():
        if not menu.switches_command(checkout):
            continue
        key = str(checkout)
        rows, why = menu.features_run(checkout, "list")
        if not isinstance(rows, list):
            log(f"WARN {checkout.name}: its switches are unread, so none was handed "
                f"({why or 'no list'})")
            continue
        handed = record.get(key)
        if handed and not any(isinstance(row, dict) and row.get("id") == handed["id"]
                              and since(row) in (None, handed["since"]) for row in rows):
            del record[key]    # out of the code, or one of that id went on for everyone anew
            handed = None
        if handed:
            if now - handed["at"] < AGAIN:
                continue
            feature, proof, text = handed["id"], handed["since"], handed["line"]
        else:
            proven = due(rows, now)
            if not proven:
                continue
            feature, proof, text = proven[0]["id"], since(proven[0]), line(checkout.name, proven[0])
        seat = seat_for(checkout)
        if seat is None:
            log(f"{checkout.name}: switch {feature} is proven; no open seat to hand it to")
            continue
        # in hand before its line is queued: a record that cannot be saved hands nothing
        record[key] = {"id": feature, "since": proof, "at": now, "seat": seat["name"],
                       "line": text}
        write(record)
        refused = tell.queue(seat["name"], text)
        if refused:
            if handed:
                record[key] = handed
            else:
                del record[key]
            log(f"WARN {checkout.name}: switch {feature} was not handed: {refused}")
        else:
            log(f"{checkout.name}: switch {feature} is proven; handed to {seat['name']}")
    write(record)

"""A feature switch on for everyone for two weeks is proven, and comes out of the code.

A production project names its switches with one command, `features:` in its AGENTS.md. A row
its `list` prints with `everyone` on and `everyone_since` (when it last went on for everyone,
ISO 8601) at least PROVEN ago is due. Once every EVERY the tick reads each repository's list
once, however many of its checkouts sit under ~/code, and hands the longest-due switch to the
newest open seat filed under the project, through the queue `ak tell` fills. One switch at a
time: the next is handed once the last has left the list, which the project's own deploy does
when the code no longer reads it, and one still listed AGAIN after it was handed is handed
again. With no open seat there, nothing is handed and the next read tries again.
"""

from datetime import datetime
import json
import time

from . import config, orch, tell

PROVEN = 14 * 86400    # the owner's two weeks: on for everyone this long, a switch is proven
EVERY = 3600           # how often the lists are read for this
AGAIN = 86400          # a handed switch still listed this long after is handed again


def path():
    return config.STATE / "retire.json"


def read():
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(data):
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path())


def since(row):
    """When that row last went on for everyone, in epoch seconds, or None while it is not."""
    stamp = row.get("everyone_since")
    if row.get("everyone") is not True or not isinstance(stamp, str):
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.timestamp() if at.tzinfo else None


def due(rows, now):
    """The rows proven by `now`, longest on for everyone first."""
    stamped = [(since(row), row["id"], row) for row in rows
               if isinstance(row, dict) and isinstance(row.get("id"), str)]
    return [row for at, _, row in sorted(item for item in stamped if item[0] is not None)
            if now - at >= PROVEN]


def line(row):
    day = time.strftime("%-d %b", time.localtime(since(row)))
    return (f"[from ak, not the owner] The `{row['id']}` switch has been on for everyone since "
            f"{day}: two weeks or more, so it is proven. Take it out of the code, keeping the feature as "
            "everyone has it now. Once the deploy drops it from the switch list, ak hands over "
            "the next.")


def projects():
    """{main checkout: its checkouts under ~/code}, for each repository that names switches."""
    from . import menu, run   # here, not at the top: both are the whole screen and loop
    found = {}
    for checkout in orch.checkouts():
        found.setdefault(run.main_checkout(checkout), []).append(checkout)
    return {home: checkouts for home, checkouts in found.items() if menu.switches_command(home)}


def seat_for(checkouts):
    """The newest open seat filed under one of those checkouts, or None."""
    records = config.session_records()
    seats = [session for session in orch.sessions()
             if not any(session.get(key) for key in orch.CLOSED)
             and orch.checkout_of((records.get(session["name"]) or {}).get("repo")) in checkouts]
    return max(seats, key=lambda session: (session.get("created") or 0, session["name"]),
               default=None)


def hand(log, now=None):
    """The tick's pass: at most one proven switch per project handed to a seat there."""
    from . import menu   # here, not at the top: the menu is the whole screen
    now = time.time() if now is None else now
    record = read()
    if now - record.get("asked", 0) < EVERY:
        return
    record["asked"] = now
    for home, checkouts in projects().items():
        entry = record.setdefault(str(home), {})
        rows, why = menu.features_run(home, "list")
        if not isinstance(rows, list):
            log(f"WARN {home.name}: its switches are unread, so none was handed ({why or 'no list'})")
            continue
        proven = due(rows, now)
        handed = entry.get("handed") or {}
        if not proven:
            entry.pop("handed", None)
            continue
        if (handed.get("id") in {row["id"] for row in proven}
                and now - handed.get("at", 0) < AGAIN):
            continue
        seat = seat_for(checkouts)
        if seat is None:
            log(f"{home.name}: switch {proven[0]['id']} is proven; no open seat to hand it to")
            continue
        refused = tell.queue(seat["name"], line(proven[0]))
        if refused:
            log(f"WARN {home.name}: switch {proven[0]['id']} was not handed: {refused}")
            continue
        entry["handed"] = {"id": proven[0]["id"], "at": now, "seat": seat["name"]}
        log(f"{home.name}: switch {proven[0]['id']} is proven; handed to {seat['name']}")
    write(record)

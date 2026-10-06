"""A feature switch on for everyone for two weeks is proven, and comes out of the code.

A production project names its switches with one command, `features:` in its AGENTS.md. A row
its `list` prints with `everyone` on and `everyone_since` (when it last went on for everyone,
ISO 8601 UTC) at least PROVEN ago is proven. Once every EVERY the tick reads the list of each
checkout under ~/code that declares one, and tells the newest open seat filed under it every
switch that list shows proven, longest first, in one line through the queue `ak tell` fills.
The line names the project, so it holds wherever it lands. A checkout is told again AGAIN
after, while any is still listed so, until the project's own deploy drops each from the list
once the code no longer reads it. What a seat was told stands: a switch turned off after is
still taken out, since turning a proven switch off is a code change (the owner, 5 Oct 2026);
the list just no longer names it. A list that cannot be read, or a checkout with no open seat,
is tried again at the next read.

All that is kept is when each checkout was last told, so nothing here can go stale: what is
told is what the list shows that moment. A checkout is a project, as everywhere in ak, and
nothing guesses which are one: one project checked out twice, with open seats filed under both,
is told in each.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from . import config, orch, tell

PROVEN = 14 * 86400    # the owner's two weeks: on for everyone this long, a switch is proven
EVERY = 3600           # how often the lists are read for this
AGAIN = 86400          # a checkout told is told again this long after, while any is still listed


def path():
    return config.STATE / "retire.json"


def read():
    """When the lists were last read ("asked") and each checkout last told; {} before the first,
    and for a record that is not one, which costs at most a line told again, as does a time in
    it that is not past."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    if not (isinstance(data, dict) and all(isinstance(at, (int, float)) for at in data.values())):
        return {}
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
    """The switch rows proven by `now`, longest on for everyone first."""
    stamped = [(since(row), str(row["id"]), row) for row in rows]
    return [row for at, _, row in sorted((item for item in stamped if item[0] is not None),
                                         key=lambda item: item[:2])
            if now - at >= PROVEN]


def line(project, rows):
    """What a seat on that project is told of those proven rows; one longer than a told line may
    hold is written to a file the line names instead, as `ak tell` asks of a longer line."""
    named = ", ".join(f"`{row['id']}` since {time.strftime('%-d %b', time.localtime(since(row)))}"
                      for row in rows)
    text = (f"[from ak, not the owner] In {project}, these switches have been on for everyone two "
            f"weeks or more, so they are proven: {named}. Take each out of {project}'s code, so "
            "everyone keeps the feature for good. ak says this again each day one is still "
            "listed.")
    if not tell.too_long(text):
        return text
    whole = config.STATE / "retire" / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.txt"
    whole.parent.mkdir(parents=True, exist_ok=True)
    whole.write_text(text + "\n", encoding="utf-8")
    try:
        shown = f"~/{whole.relative_to(Path.home())}"   # as long however deep the home is
    except ValueError:
        shown = whole
    return (f"[from ak, not the owner] Proven feature switches are yours to take out of the code: "
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
    """The tick's pass: each checkout not told for AGAIN is told what its list shows proven."""
    from . import menu   # here, not at the top: the menu is the whole screen
    now = time.time() if now is None else now
    record = read()
    if 0 <= now - record.get("asked", 0) < EVERY:
        return
    record["asked"] = now
    for checkout in orch.checkouts():
        key = str(checkout)
        if 0 <= now - record.get(key, 0) < AGAIN or not menu.switches_command(checkout):
            continue
        answer, why = menu.features_run(checkout, "list")
        rows = menu.switch_rows(answer)
        if rows is None:
            log(f"WARN {checkout.name}: its switches are unread, so none was told "
                f"({why or 'no list'})")
            continue
        proven = due(rows, now)
        if not proven:
            continue
        ids = ", ".join(str(row["id"]) for row in proven)
        seat = seat_for(checkout)
        if seat is None:
            log(f"{checkout.name}: proven switches {ids}; no open seat to tell")
            continue
        refused = tell.queue(seat["name"], line(checkout.name, proven))
        if refused:
            log(f"WARN {checkout.name}: proven switches {ids} were not told: {refused}")
            continue
        record[key] = now
        write(record)
        log(f"{checkout.name}: proven switches {ids}; told {seat['name']}")
    write(record)

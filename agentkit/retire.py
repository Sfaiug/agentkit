"""A feature switch on for everyone for two weeks is proven, and comes out of the code.

A production project names its switches with one command, `features:` in its AGENTS.md. A row
its `list` prints with `everyone` on and `everyone_since` (when it last went on for everyone,
ISO 8601 UTC) at least PROVEN ago is proven. Once every EVERY the tick reads the list of each
checkout under ~/code that declares one, and writes an open line into the plan of a seat filed
under it for every switch that list shows proven, and for every switch on for everyone that it
cannot prove because its row gives no `everyone_since`. A switch goes to the newest seat whose
open plan already names it, since that seat has it in hand; the rest go to the newest seat.
The line's check is the project's own switch list: it fails while the list still shows the
switch (or, for an unproven one, shows it without an `everyone_since`), and the plan ticks it by
itself once the project's deploy drops the row, which happens once the code no longer reads it.
An open line that already holds that check is not written twice (`plan.add`), so a seat is told
nothing again. What a plan line says stands: a switch turned off after is still taken out,
since turning a proven switch off is a code change (the owner, 5 Oct 2026); the list just no
longer names it. A list that cannot be read, or a checkout with no open seat, is tried again at
the next read. Nothing is typed into a seat: a plan line is read when the seat looks at its plan.

All that is kept is when each checkout's lines were last written, so nothing here can go
stale: what is written is what the list shows that moment. A checkout is a project, as
everywhere in ak, and nothing guesses which are one: one project checked out twice, with open
seats filed under both, gets its lines in each.
"""

from datetime import datetime, timezone
import json
import re
import shlex
import time

from . import config, orch, plan

PROVEN = 14 * 86400    # the owner's two weeks: on for everyone this long, a switch is proven
EVERY = 3600           # how often the lists are read for this
AGAIN = 86400          # a checkout whose lines were written is read again this long after


def path():
    return config.STATE / "retire.json"


def read():
    """When the lists were last read ("asked") and each checkout's lines last written; {} before
    the first, and for a record that is not one, which costs at most a list read again, as does
    a time in it that is not past."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    try:
        return {key: float(at) for key, at in data.items()} if isinstance(data, dict) else {}
    except (TypeError, ValueError, OverflowError):
        return {}


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


def undated(rows):
    """The rows on for everyone whose list gives no readable `everyone_since`: a list built to the
    contract before that field, which could never prove them."""
    return [row for row in rows if row.get("everyone") is True and since(row) is None]


def outcome(project, row, proven):
    """The plan line's words for that switch: what the seat is to make true.  Plain words, as a
    plan line holds them: no backtick and no `·`."""
    name = " ".join(str(row["id"]).split())
    if proven:
        day = time.strftime("%-d %b", time.localtime(since(row)))
        return (f"{project}'s switch {name} is out of the code: on for everyone since {day}, "
                "so proven, and everyone keeps the feature for good")
    return (f"{project}'s switch list gives {name} an everyone_since (when it last went on for "
            "everyone, ISO 8601 UTC, or null while it is not), so ak can tell when it is proven")


def check(command, row, proven):
    """The line's check, one shell line over the project's own switch list: it fails while the
    list still shows that switch, or shows it with no `everyone_since`."""
    test = ("sys.exit(1 if any(str(r.get('id')) == sys.argv[1] for r in rows) else 0)" if proven
            else "sys.exit(0 if any(str(r.get('id')) == sys.argv[1] and "
                 "isinstance(r.get('everyone_since'), str) for r in rows) else 1)")
    body = ("import json, sys; rows = [r for r in json.load(sys.stdin) if isinstance(r, dict)]; "
            + test)
    return f"{command} list | python3 -c \"{body}\" {shlex.quote(str(row['id']))}"


def seats_for(checkout):
    """The open seats filed under that checkout, newest first."""
    records = config.session_records()
    seats = [session for session in orch.sessions()
             if not any(session.get(key) for key in orch.CLOSED)
             and orch.checkout_of((records.get(session["name"]) or {}).get("repo")) == checkout]
    return sorted(seats, key=lambda session: (session.get("created") or 0, session["name"]),
                  reverse=True)


def planned(name):
    """What that seat's open plan lines set out to do, as one text; none from a plan nothing can
    read."""
    try:
        return "\n".join(plan.LINE.match(line)["what"] for line in plan.open_lines(name))
    except config.Error:
        return ""


def owners(seats, rows):
    """Each row's seat: the newest whose open plan names that switch, since it already has it in
    hand, else the newest of all."""
    plans = {seat["name"]: planned(seat["name"]) for seat in seats}
    found = {}
    for row in rows:
        word = re.compile(rf"(?<![\w-]){re.escape(str(row['id']))}(?![\w-])")
        name = next((seat["name"] for seat in seats if word.search(plans[seat["name"]])),
                    seats[0]["name"])
        found[str(row["id"])] = name
    return found


def hand(log, now=None):
    """The tick's pass: each checkout not written for AGAIN gets a plan line per switch its list
    shows proven or cannot prove, in a seat filed under it."""
    from . import menu   # here, not at the top: the menu is the whole screen
    now = time.time() if now is None else now
    record = read()
    if 0 <= now - record.get("asked", 0) < EVERY:
        return
    record["asked"] = now
    for checkout in orch.checkouts():
        key = str(checkout)
        command = menu.switches_command(checkout)
        if 0 <= now - record.get(key, 0) < AGAIN or not command:
            continue
        answer, why = menu.features_run(checkout, "list")
        rows = menu.switch_rows(answer)
        if rows is None:
            log(f"WARN {checkout.name}: its switches are unread, so none was planned "
                f"({why or 'no list'})")
            continue
        proven, unproven = due(rows, now), undated(rows)
        if not (proven or unproven):
            continue
        about = "; ".join(f"{what} {', '.join(str(row['id']) for row in found)}" for what, found in (
            ("proven switches", proven), ("on for everyone with no everyone_since", unproven))
            if found)
        seats = seats_for(checkout)
        if not seats:
            log(f"{checkout.name}: {about}; no open seat to plan it in")
            continue
        owner = owners(seats, proven + unproven)
        written, refused = [], []
        for rows_of, is_proven in ((proven, True), (unproven, False)):
            for row in rows_of:
                name = owner[str(row["id"])]
                try:
                    plan.add(name, outcome(checkout.name, row, is_proven),
                             check(command, row, is_proven), repo=checkout)
                except config.Error as exc:
                    refused.append(f"{name}: {row['id']}: {exc}")
                    continue
                if name not in written:
                    written.append(name)
        if refused:
            log(f"WARN {checkout.name}: {about}; not planned: {'; '.join(refused)}")
            continue
        record[key] = now
        write(record)
        log(f"{checkout.name}: {about}; planned in {', '.join(written)}")
    write(record)

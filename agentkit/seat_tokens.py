"""Seat usage and transcript cursors, committed together so a retry counts nothing twice."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from . import config, harness, history

# Each table's columns, in order: a table made before a column was added gets it at its end.
# A usage row's account is the login of the seat that owned its conversation when the tick read
# it; its model and counts by type are NULL where its harness does not tell them; its listed_usd
# is what its counts cost at listed prices as it was written, as a turn's row's
# (`history.TURN_USAGE_SCHEMA`); its orchestrator and effort are `orchestrating`'s.  A turn row
# is a seat's turn as its harness timed it, at the moment it ended, its event, repo, account,
# orchestrator and effort as a usage row read from that file in that tick holds them.
TABLES = {
    "seat_sources": ("path TEXT PRIMARY KEY", "harness TEXT", "repo TEXT", "cursor TEXT",
                     "account TEXT"),
    "seat_usage": ("event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "tokens INTEGER",
                   "account TEXT", "model TEXT", "input INTEGER", "cache_write INTEGER",
                   "cache_read INTEGER", "output INTEGER", "listed_usd REAL", "orchestrator TEXT",
                   "effort TEXT"),
    "seat_turns": ("event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "seconds REAL",
                   "account TEXT", "orchestrator TEXT", "effort TEXT"),
}


def orchestrating(cfg, seat):
    """The model and effort seat record `seat` orchestrates with, as a run it launched now would
    keep them as its `orchestrator` and `orchestrator_effort`: neither where that run would keep
    no effort, as for a model `cfg` does not hold.  Read from the record as the tick reading a
    line found it, so nothing stored needs repair when the seat, its models or its conversations
    change: a line the seat wrote before a move, of a source that tick found the seat still
    owning (`seat_token_sources`), is filed under what it found the seat moved to.  The owner,
    21 Nov 2026, left it so ("Drop it"): two designs keeping what the seat left failed seven
    reviews on a record edited beside a tick, for a seat's lines of the stretch between two
    ticks, each move."""
    model = seat.get("orchestrator")
    try:
        effort = config.launched_effort(config.run_marks(cfg, seat), model, "orchestrator")
    except TypeError:       # efforts ak did not write: a number, or a word where it writes a table
        effort = None
    return (None, None) if effort is None else (model, effort)


def read(since, until):
    from . import orch

    seats = config.session_records()
    if not seats:
        try:
            with closing(history._connect(readonly=True)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'seat_sources'").fetchone():
                    return [], []
        except (OSError, sqlite3.Error):
            return [], []

    def collect(db):
        for table, columns in TABLES.items():
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(columns)})")
            have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column.split()[0] not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        db.execute("CREATE INDEX IF NOT EXISTS seat_usage_at ON seat_usage(at)")
        missing, owners, marks = [], {}, {}
        cfg, priced = orch.loaded(), history._listed_usd()
        for name, seat in seats.items():
            plugin = orch.seat_plugin(seat, cfg=cfg)
            try:
                sources = plugin.seat_token_sources(seat)
            except OSError:
                sources = None
            if sources is None or (not sources and seat.get("conversation")):
                missing.append(f"{name} ({plugin.name or 'unknown harness'})")
                continue
            for path in sources:
                path, login = path if isinstance(path, tuple) else (path, seat.get("account"))
                path = str(Path(path).resolve())
                owners[path], marks[path] = name, orchestrating(cfg, seat)
                db.execute("INSERT INTO seat_sources VALUES (?, ?, ?, '{}', ?) ON CONFLICT(path) "
                           "DO UPDATE SET repo = excluded.repo, account = excluded.account",
                           (path, plugin.name, Path(seat.get("repo") or "").name,
                            login or config.DEFAULT_ACCOUNT))
        # Keep reading known conversations after a clear, rename, harness change or seat removal.
        for source, adapter, repo, saved, account in db.execute(
                "SELECT * FROM seat_sources").fetchall():
            cursor = json.loads(saved)
            cursor["source"] = source
            orchestrator, effort = marks.get(source, (None, None))
            plugin = harness.load(adapter)
            try:
                whole = plugin.seat_token_entries(source)
                entries = (lines(source, cursor) if whole is None
                           else ((f"{source}:{n}", entry) for n, entry in enumerate(whole)))
                for place, entry in entries:
                    # An entry SQLite cannot hold, a lone surrogate or a number past its
                    # integers or a float, raises before it writes; the entries after it go on.
                    try:
                        at, key, seconds = plugin.seat_turn(entry) or (None,) * 3
                        if (at := harness.moment(at)) is not None:
                            # As first filed: a file read again from its start changes no turn.
                            db.execute("INSERT OR IGNORE INTO seat_turns VALUES "
                                       "(?, ?, ?, ?, ?, ?, ?)",
                                       (f"{adapter}:{key or place}", repo, float(at), seconds,
                                        account, orchestrator, effort))
                    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                        pass
                    kept = dict(cursor)
                    try:
                        usage = plugin.seat_token_usage(entry, cursor)
                        if usage is None:
                            continue
                        at, key, tokens, model, counts = usage
                        if ((at := harness.moment(at)) is not None
                                and isinstance(tokens, int) and tokens >= 0):
                            counts = counts or [None] * 4
                            # A repeat counting more replaces all its line set, so the counts,
                            # model, login, dollars and orchestrating stay those of the line
                            # that set the tokens.  A source read whole is met again at every
                            # reading: its entries stay as first filed, as a turn does.
                            db.execute("INSERT INTO seat_usage VALUES "
                                       "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                                       "ON CONFLICT(event) DO UPDATE SET "
                                       "tokens = excluded.tokens, account = excluded.account, "
                                       "model = excluded.model, input = excluded.input, "
                                       "cache_write = excluded.cache_write, "
                                       "cache_read = excluded.cache_read, "
                                       "output = excluded.output, "
                                       "listed_usd = excluded.listed_usd, "
                                       "orchestrator = excluded.orchestrator, "
                                       "effort = excluded.effort "
                                       "WHERE excluded.tokens > tokens AND ?",
                                       (f"{adapter}:{key or place}", repo, at, tokens, account,
                                        model, *counts, priced(model, counts), orchestrator,
                                        effort, whole is None))
                            continue
                    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                        pass
                    # A line filing no row moves the cursor by nothing: a running count then
                    # grows from the last line filed.
                    cursor.clear()
                    cursor.update(kept)
                db.execute("UPDATE seat_sources SET cursor = ? WHERE path = ?",
                           (json.dumps(cursor), source))
            except OSError:
                if source in owners:
                    missing.append(f"{owners[source]} ({adapter})")
        rows = db.execute("SELECT repo, at, tokens FROM seat_usage WHERE at >= ? AND at <= ?",
                          (since, until)).fetchall()
        return rows, sorted(set(missing))

    return history._write(collect) or ([], ["seat usage unreadable"])


def lines(source, cursor):
    """(where it starts, its entry) of each whole line of that log past the cursor, the cursor
    moved past them all once all are given: the log read from its start where another file is at
    its path or it shrank."""
    with Path(source).open("rb") as stream:
        stat = os.fstat(stream.fileno())
        identity = [stat.st_dev, stat.st_ino]
        offset = cursor.get("offset", 0)
        if cursor.get("identity") != identity or offset > stat.st_size:
            offset = 0
        stream.seek(offset)
        while stream.tell() < stat.st_size:
            line = stream.readline(stat.st_size - stream.tell())
            if not line.endswith(b"\n"):
                break       # the harness may still be writing this line
            start, offset = offset, stream.tell()
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            yield f"{source}:{start}", entry
        cursor.update(identity=identity, offset=offset)

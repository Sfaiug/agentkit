"""Seat usage and transcript cursors, committed together so a retry counts nothing twice."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from . import config, harness, history

# Each table's columns, in order: a table made before a column was added gets it at its end.
# A usage row's account is the login of the seat that owned its conversation when the tick read
# it; its model and counts by type are NULL where its harness does not tell them.
TABLES = {
    "seat_sources": ("path TEXT PRIMARY KEY", "harness TEXT", "repo TEXT", "cursor TEXT",
                     "account TEXT"),
    "seat_usage": ("event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "tokens INTEGER",
                   "account TEXT", "model TEXT", "input INTEGER", "cache_write INTEGER",
                   "cache_read INTEGER", "output INTEGER"),
}


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
        missing, owners = [], {}
        cfg = orch.loaded()
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
                path = str(Path(path).resolve())
                owners[path] = name
                db.execute("INSERT INTO seat_sources VALUES (?, ?, ?, '{}', ?) ON CONFLICT(path) "
                           "DO UPDATE SET repo = excluded.repo, account = excluded.account",
                           (path, plugin.name, Path(seat.get("repo") or "").name,
                            seat.get("account") or config.DEFAULT_ACCOUNT))
        # Keep reading known conversations after a clear, rename, harness change or seat removal.
        for source, adapter, repo, saved, account in db.execute(
                "SELECT * FROM seat_sources").fetchall():
            cursor = json.loads(saved)
            cursor["source"] = source
            try:
                with Path(source).open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    identity = [stat.st_dev, stat.st_ino]
                    offset = cursor.get("offset", 0)
                    if cursor.get("identity") != identity or offset > stat.st_size:
                        offset = 0
                    stream.seek(offset)
                    plugin = harness.load(adapter)
                    while stream.tell() < stat.st_size:
                        line = stream.readline(stat.st_size - stream.tell())
                        if not line.endswith(b"\n"):
                            break       # the harness may still be writing this line
                        start, offset = offset, stream.tell()
                        try:
                            usage = plugin.seat_token_usage(json.loads(line), cursor)
                            if usage is None:
                                continue
                            at, key, tokens, model, counts = usage
                            at = harness.moment(at)
                            if at is None or not isinstance(tokens, int) or tokens < 0:
                                continue
                        except (ValueError, TypeError, KeyError, AttributeError):
                            continue
                        event = f"{adapter}:{key or f'{source}:{start}'}"
                        # A repeat counting more replaces all its line set, so the counts,
                        # model and login stay those of the line that set the tokens.
                        db.execute("INSERT INTO seat_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                                   "ON CONFLICT(event) DO UPDATE SET tokens = excluded.tokens, "
                                   "account = excluded.account, model = excluded.model, "
                                   "input = excluded.input, cache_write = excluded.cache_write, "
                                   "cache_read = excluded.cache_read, output = excluded.output "
                                   "WHERE excluded.tokens > tokens",
                                   (event, repo, at, tokens, account, model,
                                    *(counts or [None] * 4)))
                    cursor.update(identity=identity, offset=offset)
                    db.execute("UPDATE seat_sources SET cursor = ? WHERE path = ?",
                               (json.dumps(cursor), source))
            except OSError:
                if source in owners:
                    missing.append(f"{owners[source]} ({adapter})")
        rows = db.execute("SELECT repo, at, tokens FROM seat_usage WHERE at >= ? AND at <= ?",
                          (since, until)).fetchall()
        return rows, sorted(set(missing))

    return history._write(collect) or ([], ["seat usage unreadable"])

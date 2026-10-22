"""Best-effort SQLite history for completed and running agentkit runs."""

import contextlib
import fcntl
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from statistics import median

from . import config, gitcall, host, record

_LOCK = threading.Lock()
SUMMARY_TASKS = 20    # the status line looks back over this many finished runs per repo
SUMMARY_WORDS = 400   # ... and contrasts tasks over this many words outside the checks block
SUMMARY_POINTS = 3    # ... and tasks over this many numbered goal points, by median rounds
# The repositories the smoke and e2e suites clone: their runs are tests, never work to learn from.
SANDBOX_REPOS = ("agentkit-smoke", "agentkit-e2e")
# The condition every statistic reads rows under: no stopped run and no suite's (`suite_run`).
# Other values stay as written, except duplicated Codex tokens repaired by `_recount_tokens`.
REAL_WORK = "COALESCE(final_state,'') != 'stopped' AND NOT suite_run(run_id, repo)"
STEP_COLUMNS = {"executor": "executor_seconds", "done-when": "done_when_seconds",
                "reviewer": "reviewer_seconds", "merge": "merge_seconds"}
# The waits a run marks, each summed across its resumes; NULL on a row written before them.
# A landing check's wait for a heavy-suite turn is the lander's, inside the run's line wait.
WAIT_COLUMNS = {"slot": "slot_wait_seconds", "suite": "suite_wait_seconds",
                "merge": "merge_wait_seconds", "lander": "lander_wait_seconds"}
_OPEN = {}     # run_id -> [step, since, opened]: the step this process runs, counted up to
               # `since`, and its phase row's start
_OPEN_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repo TEXT,
    executor TEXT,
    reviewer TEXT,
    rounds_used INTEGER,
    final_state TEXT,
    verdict TEXT,
    started_at REAL,
    finished_at REAL,
    executor_seconds REAL,
    done_when_seconds REAL,
    reviewer_seconds REAL,
    merge_seconds REAL,
    total_seconds REAL,
    executor_tokens INTEGER,
    reviewer_tokens INTEGER,
    peak_rss_mb REAL,
    session TEXT,
    task_words INTEGER,
    task_points INTEGER,
    task_checks INTEGER,
    task_files TEXT,
    orchestrator TEXT,
    changed_lines INTEGER,
    slot_wait_seconds REAL,
    suite_wait_seconds REAL,
    merge_wait_seconds REAL,
    lander_wait_seconds REAL
)
"""

MIGRATIONS = (("task_words", "INTEGER"), ("task_points", "INTEGER"),
              ("task_checks", "INTEGER"), ("task_files", "TEXT"), ("orchestrator", "TEXT"),
              ("changed_lines", "INTEGER"), ("live_at", "REAL"), ("slot_wait_seconds", "REAL"),
              ("suite_wait_seconds", "REAL"), ("merge_wait_seconds", "REAL"),
              ("lander_wait_seconds", "REAL"), ("rules_bytes", "INTEGER"), ("change", "TEXT"),
              ("merge_sha", "TEXT"), ("parked_at", "REAL"), ("first_review_lines", "INTEGER"),
              ("landing_breaks", "INTEGER"), ("broke_after_merge", "TEXT"),
              ("own_orchestrator", "TEXT"), ("executor_effort", "TEXT"),
              ("own_orchestrator_effort", "TEXT"))

# One row per phase of a run, in order: each step a process ran (`STEP_COLUMNS`) and each wait
# it counted (`WAIT_COLUMNS`, named `<wait> wait`), its end moved by each checkpoint or poll and
# by its close, so a row never lacks an end and a loop that died counts what its column counts.
# A run with no row keeps no phases.
PHASES_SCHEMA = """
CREATE TABLE IF NOT EXISTS phases (
    run_id TEXT,
    phase TEXT,
    started_at REAL,
    ended_at REAL,
    PRIMARY KEY (run_id, phase, started_at)
)
"""

REVIEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    run_id TEXT,
    review_id TEXT,
    harness TEXT,
    model TEXT,
    blocking INTEGER,
    followup INTEGER,
    note INTEGER,
    PRIMARY KEY (run_id, review_id)
)
"""
# One finished review per row: the identity that ran it, its weighed counts, and since these
# columns its round, the round's verdict and the effort it ran at (`record_review`).
REVIEW_MIGRATIONS = (("round", "INTEGER"), ("verdict", "TEXT"), ("effort", "TEXT"))

# The owner's time, one row per moment and no seat named: each is whole when written, so no
# rename, reused name or order of hooks can change it later.
OWNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
    at REAL,
    kind TEXT,
    waited REAL
)
"""
# A seat's done, one row each, keyed by its harness and conversation so a rename or a reused
# name moves nothing: `began` is the owner's first message there since its previous done, NULL
# where ak cannot know it or the done finished nothing new.  `work` fingerprints the seat's
# finished work at that done (`notify._intent`), NULL on a row from before it.  `kept` holds
# since when dones are kept: 0 for a history begun with them, else the moment an older one first
# met them, before which a conversation's dones went unrecorded.
DONES_SCHEMA = """
CREATE TABLE IF NOT EXISTS dones (
    conversation TEXT,
    at REAL,
    began REAL
)
"""
DONE_MIGRATIONS = (("work", "TEXT"),)
KEPT_SCHEMA = "CREATE TABLE IF NOT EXISTS kept (since REAL)"
# The runs a seat started between its owner's first message and its done, one row each: the
# changes whose going live is the intent's.
DONE_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS done_runs (
    conversation TEXT,
    at REAL,
    run_id TEXT
)
"""


def path():
    """The history database follows the configured HOME, including test homes."""
    return config.HOME / "history.db"


def _connect(*, readonly=False):
    database = path()
    if readonly:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.create_function("suite_run", 2, suite_run)     # what REAL_WORK reads by
        return connection
    connection = sqlite3.connect(database, timeout=2)
    connection.execute(KEPT_SCHEMA)
    # Read before `runs` is made, in the statement that writes it, so two first connects agree;
    # committed at once, as the tables below are made outside a transaction.
    if not connection.execute("SELECT 1 FROM kept").fetchone():
        connection.execute("INSERT INTO kept (since) SELECT CASE WHEN EXISTS (SELECT 1 FROM sqlite_master "
                           "WHERE name = 'runs') THEN ? ELSE 0 END WHERE NOT EXISTS (SELECT 1 FROM kept)",
                           (time.time(),))
        connection.commit()
    connection.execute(SCHEMA)
    connection.execute(PHASES_SCHEMA)
    connection.execute(REVIEWS_SCHEMA)
    connection.execute(OWNER_SCHEMA)
    connection.execute(DONES_SCHEMA)
    connection.execute(DONE_RUNS_SCHEMA)
    for table, migrations in (("runs", MIGRATIONS), ("reviews", REVIEW_MIGRATIONS),
                              ("dones", DONE_MIGRATIONS)):
        have = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, kind in migrations:
            if name not in have:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    if connection.execute("PRAGMA user_version").fetchone()[0] < 2:
        _recount_tokens(connection)
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    return connection


def _recount_tokens(connection):
    """Repair a recorded prefix of kept turns, leaving unmatched totals alone."""
    from .harness.codex import token_counts
    rows = connection.execute("SELECT run_id, executor_tokens, reviewer_tokens FROM runs").fetchall()
    for run_id, executor, reviewer in rows:
        recorded = {"executor": executor, "reviewer": reviewer}
        raw, corrected, matched = dict.fromkeys(recorded, 0), dict.fromkeys(recorded, 0), {}
        run_dir = config.RUNS / run_id
        codex = {path: (total, spent) for path, total, spent in token_counts(run_dir)}
        for path in event_paths(run_dir):
            total, spent = codex.get(path, (None, None))
            if total is None:
                total = spent = event_tokens(path)
            if total is None:
                continue
            # All other worker turns, including landing fixers, count as executor work.
            role = "reviewer" if path.parent.name.startswith("reviewer") else "executor"
            raw[role] += total
            corrected[role] += spent
            # A log can flush before its finally block adds usage. Only a prefix matching
            # the row's old total identifies which reports were already recorded.
            if raw[role] == recorded[role]:
                matched[role] = corrected[role]
        for role, amount in matched.items():
            if amount != recorded[role]:
                connection.execute(
                    f"UPDATE runs SET {role}_tokens=? WHERE run_id=?",
                    (amount, run_id))


@contextlib.contextmanager
def _writing():
    """One writer of history.db at a time, across processes: runs, the tick and the menu each
    write, and sqlite's own wait gives up after its timeout and the write would be lost."""
    path().parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _write(fn, log=None):
    """Run one database mutation; history can never make a run fail."""
    try:
        with _writing():
            connection = _connect()
            try:
                result = fn(connection)
                connection.commit()
                return result
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        try:
            if log is not None:
                log(f"WARN history: {exc}")
            else:
                with (config.HOME / "history.log").open("a") as output:
                    output.write(f"WARN history: {exc}\n")
        except Exception:
            pass
        return None


def sandbox(repo):
    """Whether a repository is a test suite's throwaway, whose runs teach nothing about work.

    The suites clone `agentkit-smoke` and `agentkit-e2e`, and make every other repository they
    run in under some HOME's `.agentkit/tmp` -- the caller's, when the suite runs under a HOME
    of its own.
    """
    if not isinstance(repo, (str, os.PathLike)) or not repo:
        return False
    path = Path(repo)
    return path.name in SANDBOX_REPOS or any(
        parent.name == "tmp" and parent.parent.name == ".agentkit" for parent in path.parents)


def suite_run(run_id, repo):
    """Whether a row is a suite's run, which this agentkit never records and an older one did.

    Only the repository's name reaches the database, so a suite repository under `.agentkit/tmp`
    is known by the path its run's own record saved: read, never written back.
    """
    if sandbox(repo):
        return True
    saved = record.read_state(config.RUNS / str(run_id))
    return sandbox(saved.get("repo") if saved else None)


def start_run(run_id, *, repo=None, executor=None, reviewer=None, rounds_used=0,
              started_at=None, session=None, task_words=None, task_points=None,
              task_checks=None, task_files=None, orchestrator=None, change=None, log=None):
    """Create or refresh the durable row written before a run does work.

    A sandbox's run is never recorded: the row a launch wrote before its repository was known
    goes, and every later write finds no row to change.  The orchestrator is the launching
    seat's at the first write, whatever that seat runs by a resume.  `change` names the
    change the run belongs to (its PR, or the run it continues), which the scoreboard groups
    runs by.  A new row is followed for breaks (`add_landing_break`, `broke_after_merge`), none
    yet 0 and '', where a row from before they were recorded keeps NULL: unknown, not unbroken.
    """
    if sandbox(repo):
        def forget(connection):
            connection.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM phases WHERE run_id=?", (run_id,))
        _write(forget, log)
        return
    started_at = time.time() if started_at is None else started_at
    repo = Path(repo).name if repo else None
    values = (run_id, repo, executor, reviewer, rounds_used, "running", None, started_at,
              None, 0.0, 0.0, 0.0, 0.0, None, None, None, None, session,
              task_words, task_points, task_checks, task_files, orchestrator, 0.0, 0.0, 0.0, 0.0,
              change, 0, "")

    def insert(connection):
        connection.execute(
            "INSERT INTO runs (run_id, repo, executor, reviewer, rounds_used, final_state, verdict, "
            "started_at, finished_at, executor_seconds, done_when_seconds, reviewer_seconds, "
            "merge_seconds, total_seconds, executor_tokens, reviewer_tokens, peak_rss_mb, session, "
            "task_words, task_points, task_checks, task_files, orchestrator, "
            "slot_wait_seconds, suite_wait_seconds, merge_wait_seconds, lander_wait_seconds, change, "
            "landing_breaks, broke_after_merge) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET repo=COALESCE(excluded.repo,runs.repo), "
            "executor=COALESCE(excluded.executor,runs.executor), reviewer=COALESCE(excluded.reviewer,runs.reviewer), "
            "rounds_used=excluded.rounds_used, final_state='running', verdict=NULL, "
            "finished_at=NULL, total_seconds=NULL, "
            "session=COALESCE(excluded.session,runs.session), "
            "task_words=COALESCE(excluded.task_words,runs.task_words), "
            "task_points=COALESCE(excluded.task_points,runs.task_points), "
            "task_checks=COALESCE(excluded.task_checks,runs.task_checks), "
            "task_files=COALESCE(excluded.task_files,runs.task_files), "
            "orchestrator=COALESCE(runs.orchestrator,excluded.orchestrator), "
            "change=COALESCE(excluded.change,runs.change)", values)

    _write(insert, log)


def update_run(run_id, *, log=None, **fields):
    """Update known row fields, silently retaining unknown state keys."""
    _write(lambda connection: _update(connection, run_id, fields), log)


def first_review(run_id, lines, *, log=None):
    """Record the lines a change's first review reads, once: a review resumed before its verdict,
    the work grown or the target moved meanwhile, keeps the size first read."""
    _write(lambda connection: connection.execute(
        "UPDATE runs SET first_review_lines=COALESCE(first_review_lines,?) WHERE run_id=?",
        (lines, run_id)), log)


def _update(connection, run_id, fields):
    allowed = {"repo", "executor", "reviewer", "rounds_used", "final_state", "verdict",
               "started_at", "finished_at", "executor_seconds", "done_when_seconds",
               "reviewer_seconds", "merge_seconds", "total_seconds", "executor_tokens",
               "reviewer_tokens", "peak_rss_mb", "session", "task_words", "task_points",
               "task_checks", "task_files", "orchestrator", "changed_lines", "live_at",
               "rules_bytes", "merge_sha", "parked_at", "broke_after_merge", "own_orchestrator",
               "executor_effort", "own_orchestrator_effort"}
    fields = {key: value for key, value in fields.items() if key in allowed}
    if not fields:
        return
    if "repo" in fields and fields["repo"]:
        fields["repo"] = Path(fields["repo"]).name
    columns = ", ".join(f"{key}=?" for key in fields)
    values = [fields[key] for key in fields]
    connection.execute(f"UPDATE runs SET {columns} WHERE run_id=?", [*values, run_id])


def add_seconds(run_id, step, seconds, *, log=None):
    """Add one completed step duration to its cumulative column."""
    column = STEP_COLUMNS.get(step)
    if column is None or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return
    _write(lambda connection: connection.execute(
        f"UPDATE runs SET {column}=COALESCE({column},0)+? WHERE run_id=?",
        (max(0.0, seconds), run_id)), log)


def add_landing_break(run_id, *, log=None):
    """One more time a change review passed failed its tests at landing (`deliver.suite_red`)."""
    _write(lambda connection: connection.execute(
        "UPDATE runs SET landing_breaks=COALESCE(landing_breaks,0)+1 WHERE run_id=?",
        (run_id,)), log)


def add_wait(run_id, wait, seconds, at=None, *, began=None, log=None):
    """Add a wait's seconds, counted up to `at`, to its column and end its phase row there: the
    row of the wait that began at `began`, a wait counted whole without it.  A row from before
    the columns stays unrecorded."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return
    column, seconds = WAIT_COLUMNS[wait], max(0.0, seconds)
    at = time.time() if at is None else at
    began = at - seconds if began is None else began

    def add(connection):
        connection.execute(f"UPDATE runs SET {column}={column}+? WHERE run_id=?", (seconds, run_id))
        phase(connection, run_id, f"{wait} wait", began, max(began, at))
    _write(add, log)


def phase(connection, run_id, name, started_at, ended_at):
    """Write the phase row, or move its end: the one under way ends at its last checkpoint."""
    connection.execute(
        "INSERT INTO phases (run_id, phase, started_at, ended_at) "
        "SELECT run_id, ?, ?, ? FROM runs WHERE run_id=? "
        "ON CONFLICT(run_id, phase, started_at) DO UPDATE SET ended_at=excluded.ended_at",
        (name, started_at, ended_at, run_id))


def phases(run_id):
    """A run's phases in order, each `{phase, started_at, ended_at}`, the one under way ending
    at its last checkpoint; none for a run with no row."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            connection.row_factory = sqlite3.Row
            try:
                return [dict(row) for row in connection.execute(
                    "SELECT phase, started_at, ended_at FROM phases WHERE run_id=? "
                    "ORDER BY started_at, phase", (run_id,))]
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return []


def add_tokens(run_id, role, tokens, *, log=None):
    """Accumulate role tokens across rounds when an event log reports them."""
    column = "executor_tokens" if role == "executor" else "reviewer_tokens" \
        if role == "reviewer" else None
    if column is None or not isinstance(tokens, (int, float)) or isinstance(tokens, bool):
        return
    _write(lambda connection: connection.execute(
        f"UPDATE runs SET {column}=COALESCE({column},0)+? WHERE run_id=?",
        (int(tokens), run_id)), log)


def record_review(run_id, review_id, *, harness, model, blocking, followup, note, round, verdict,
                  effort=None, log=None):
    """Keep one finished review's weighed counts, its round, the round's verdict (the review's,
    after ak's overrides) and the effort it ran at, including landing reviews in the same round.

    Its output directory identifies it, so recording it again cannot count it twice; only
    runs already recorded in history can contribute.
    """
    _write(lambda connection: connection.execute(
        "INSERT INTO reviews (run_id, review_id, harness, model, blocking, followup, note, "
        "round, verdict, effort) SELECT run_id, ?,?,?,?,?,?,?,?,? FROM runs WHERE run_id=? "
        "ON CONFLICT(run_id, review_id) DO NOTHING",
        (review_id, harness, model, blocking, followup, note, round, verdict, effort, run_id)), log)


def review_counts(harness, model):
    """Finished reviews, blocking findings, follow-ups and notes for the identity that ran."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                return connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(blocking),0), COALESCE(SUM(followup),0), "
                    "COALESCE(SUM(note),0) FROM reviews JOIN runs USING (run_id) "
                    f"WHERE harness=? AND model=? AND {REAL_WORK}", (harness, model)).fetchone()
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return (0, 0, 0, 0)


def reviewed_runs(harness, model):
    """Of the runs the identity finished a review of, in whichever round and whatever became of
    the run since (its decision stood once given; a stopped run's never counts, `REAL_WORK`),
    per effort it reviewed at (None for a review from before efforts were recorded): how many,
    and how many it let through in round 1 (a round-1 review of its ended PASS).  A review from
    before its round was recorded counts for nothing."""
    _ensure_migrated()
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                counted = connection.execute(
                    "SELECT reviews.effort, COUNT(DISTINCT run_id), "
                    "COUNT(DISTINCT CASE WHEN reviews.round=1 AND reviews.verdict='PASS' "
                    "THEN run_id END) FROM reviews JOIN runs USING (run_id) "
                    f"WHERE harness=? AND model=? AND reviews.round IS NOT NULL AND {REAL_WORK} "
                    "GROUP BY reviews.effort", (harness, model))
                return {effort: (runs, let_through) for effort, runs, let_through in counted}
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {}


def merged(row):
    """Whether the run merged: its size (`changed_lines`) survives run cleanup, an older merge
    needs its record."""
    return row.get("changed_lines") is not None or bool(
        (record.read_state(config.RUNS / row["run_id"]) or {}).get("merged"))


def parks(since, until):
    """The moments the park stopped runs in the inclusive range (`parked_at`, which
    `leases.park` stamps); None where the database cannot answer.  Stopped rows, which
    `REAL_WORK` leaves out of every other count: a park is a stop."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                return [row[0] for row in connection.execute(
                    "SELECT parked_at FROM runs WHERE parked_at >= ? AND parked_at <= ?",
                    (since, until))]
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def owner_time(kind, at, waited=None, *, log=None):
    """A moment of the owner's time: a question a seat `asked` them, a card `paged` to them, or
    a question `answered`, `waited` seconds after it was asked."""
    _write(lambda connection: connection.execute(
        "INSERT INTO owner (at, kind, waited) VALUES (?, ?, ?)", (at, kind, waited)), log)


def owner(since, until):
    """The moments of the owner's time in the inclusive range, `(at, kind, waited)` as
    `owner_time` wrote them; None where the database cannot answer."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                return connection.execute("SELECT at, kind, waited FROM owner WHERE at >= ? AND at <= ?",
                                          (since, until)).fetchall()
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def seat_runs(names, since, until):
    """`(runs, reviews)` of a seat's runs, by any of its `names`, begun between `since` and
    `until`: each `(run_id, orchestrator, executor)` as it ended, and each finished review of
    them, `(harness, model)`.  None where the database cannot answer."""
    seat = f"session IN ({', '.join('?' * len(names))}) AND started_at BETWEEN ? AND ?"
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                return (connection.execute("SELECT run_id, orchestrator, executor FROM "
                                           f"runs WHERE {seat}", (*names, since, until)).fetchall(),
                        connection.execute("SELECT harness, model FROM reviews JOIN runs "
                                           f"USING (run_id) WHERE {seat}",
                                           (*names, since, until)).fetchall())
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def last_done(conversation):
    """`(last, since, work)`: that conversation's last done, None before its first, since when
    dones are kept, and that done's `work`; None where the database cannot answer."""
    return _write(lambda connection: connection.execute(
        "SELECT (SELECT MAX(at) FROM dones WHERE conversation = ?), (SELECT since FROM kept), "
        "(SELECT work FROM dones WHERE conversation = ? ORDER BY at DESC LIMIT 1)",
        (conversation, conversation)).fetchone())


def done(conversation, at, began, runs=(), *, work=None, log=None):
    """A seat's done in that conversation, the owner's first message since its previous one, the
    runs the seat started in between and the seat's finished work."""
    def insert(connection):
        connection.execute("INSERT INTO dones (conversation, at, began, work) VALUES (?, ?, ?, ?)",
                           (conversation, at, began, work))
        connection.executemany("INSERT INTO done_runs (conversation, at, run_id) VALUES (?, ?, ?)",
                               [(conversation, at, run) for run in runs])
    _write(insert, log)


def dones(since, until):
    """The dones in the inclusive range, `(at, began, live)`: `live` once each of its runs has
    ended and each that passed is live, the last of them; None while one runs, where one passed
    without going live (no merge, or no `health:` to prove it), a run has no row, or none
    passed.  None where the database cannot answer."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                # a read connection makes no table: a history no write has met since done_runs
                # came still shows its dones, none of them known live
                live = ("(SELECT CASE WHEN SUM(runs.finished_at IS NULL) "
                        "OR SUM(runs.final_state = 'pass' AND runs.live_at IS NULL) THEN NULL "
                        "ELSE MAX(CASE WHEN runs.final_state = 'pass' THEN runs.live_at END) END "
                        "FROM done_runs LEFT JOIN runs USING (run_id) "
                        "WHERE done_runs.conversation = dones.conversation AND done_runs.at = dones.at)"
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'done_runs'").fetchone()
                        else "NULL")
                return connection.execute(f"SELECT at, began, {live} FROM dones WHERE at >= ? AND at <= ?",
                                          (since, until)).fetchall()
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def open_step(run_id, step, at=None, *, log=None):
    """Count the step this process was in up to `at`, and count `step` from there."""
    at = time.time() if at is None else at
    close_step(run_id, at, log=log)
    if step in STEP_COLUMNS:
        with _OPEN_LOCK:
            _OPEN[run_id] = [step, at, at]
        # the row ends where it begins until a checkpoint or the close moves its end: a loop
        # that dies before either leaves no endless row, and counts nothing, as its column
        _write(lambda connection: phase(connection, run_id, step, at, at), log)


def close_step(run_id, at=None, *, keep=False, log=None):
    """Add the seconds this process's step ran since it was last counted; the step, or None.

    Only the process running a step counts it, so nobody adds the time after a loop died,
    parked or was stopped: the sampler's checkpoint (`keep`, which counts and carries on)
    already counted the dead loop's work to within its interval.  A retry closes its step for
    the wait and opens it again after.  Its row ends where its column is counted to, never
    earlier: a wall clock stepped back counts nothing and moves no end back.
    """
    at = time.time() if at is None else at
    with _OPEN_LOCK:
        entry = _OPEN.get(run_id) if keep else _OPEN.pop(run_id, None)
        if entry is None:
            return None
        step, since, opened = entry
        if keep:
            entry[1] = max(since, at)
    add_seconds(run_id, step, at - since, log=log)
    _write(lambda connection: phase(connection, run_id, step, opened, max(since, at)), log)
    return step


def finish_run(run_id, *, final_state=None, verdict=None, rounds_used=None,
               finished_at=None, started_at=None, peak_rss_mb=None,
               executor=None, reviewer=None, session=None, repo=None, task_files=None,
               changed_lines=None, rules_bytes=None, own_orchestrator=None,
               own_orchestrator_effort=None, log=None):
    """Record the row's final lifecycle fields and duration in one commit.

    No reader sees an ending without the run time it closes.  `own_orchestrator` names the
    model whose seat wrote the pull request the run reviewed and `own_orchestrator_effort` the
    effort it was captured at (`run.pr_writer`), none for another's or a task.
    """
    finished_at = time.time() if finished_at is None else finished_at
    values = {"final_state": final_state, "verdict": verdict, "rounds_used": rounds_used,
              "finished_at": finished_at, "peak_rss_mb": peak_rss_mb,
              "executor": executor, "reviewer": reviewer, "session": session, "repo": repo,
              "task_files": task_files, "changed_lines": changed_lines,
              "rules_bytes": rules_bytes, "own_orchestrator": own_orchestrator,
              "own_orchestrator_effort": own_orchestrator_effort}
    values = {key: value for key, value in values.items() if value is not None}
    peak = values.pop("peak_rss_mb", None)

    def publish(connection):
        _update(connection, run_id, values)
        if peak is not None:
            connection.execute(
                "UPDATE runs SET peak_rss_mb=MAX(COALESCE(peak_rss_mb,0), ?) WHERE run_id=?",
                (peak, run_id))
        if started_at is not None:
            # the earliest start stays: a loop restamps its record's start once it wins its
            # slot, and the wait for that slot is run time too
            connection.execute(
                "UPDATE runs SET started_at=COALESCE(MIN(started_at, ?), ?) WHERE run_id=?",
                (started_at, started_at, run_id))
        connection.execute(
            "UPDATE runs SET total_seconds=CASE WHEN started_at IS NULL THEN total_seconds "
            "ELSE MAX(0, ?-started_at) END WHERE run_id=?", (finished_at, run_id))

    _write(publish, log)


def sample_rss(run_id, pid=None, *, log=None):
    """Sample the loop process tree from procfs and retain the largest RSS."""
    pid = os.getpid() if pid is None else int(pid)
    try:
        children = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            stat = host.proc_stat(entry.name)
            if stat is not None:
                children.setdefault(stat.ppid, []).append(int(entry.name))
        pids, todo = set(), [pid]
        while todo:
            current = todo.pop()
            if current in pids:
                continue
            pids.add(current)
            todo.extend(children.get(current, ()))
        mb = sum(host.resident_bytes(current) or 0 for current in pids) / (1024 * 1024)
    except (OSError, ValueError, TypeError):
        return None
    _write(lambda connection: connection.execute(
        "UPDATE runs SET peak_rss_mb=MAX(COALESCE(peak_rss_mb,0), ?) WHERE run_id=?",
        (mb, run_id)), log)
    return mb


def get(run_id):
    """Return one row as a plain mapping for machine-readable run status."""
    _ensure_migrated()
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                return dict(row) if row else None
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def _ensure_migrated():
    """Bring an old database up to the current schema, best effort.

    Reads open read-only, so a database last written before the task-size columns
    existed would stay unreadable to them until some later write migrates it.  A
    database that cannot be migrated -- read-only, missing -- is left alone, and
    the read that asked goes on to fail soft as it always has.
    """
    try:
        if not path().exists():
            return
        with _writing():
            _connect().close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass


def finished_repos():
    """Distinct repositories with at least one finished run, sorted by name."""
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                return [row[0] for row in connection.execute(
                    "SELECT DISTINCT repo FROM runs WHERE finished_at IS NOT NULL "
                    f"AND repo IS NOT NULL AND {REAL_WORK} ORDER BY repo")]
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return []


def size_summary(repo, limit=SUMMARY_TASKS):
    """Median rounds for a repository's last finished tasks, overall and for big ones.

    Returns (overall, over_words, over_points): the median rounds_used over the runs,
    over those whose task was longer than SUMMARY_WORDS words outside the checks block,
    and over those with more than SUMMARY_POINTS numbered goal points.  Each is None
    where no finished run qualifies, and the whole answer is None where none finished.
    """
    _ensure_migrated()
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                rows = connection.execute(
                    "SELECT rounds_used, task_words, task_points FROM runs "
                    "WHERE repo=? AND finished_at IS NOT NULL AND rounds_used IS NOT NULL "
                    f"AND {REAL_WORK} "
                    "ORDER BY finished_at DESC LIMIT ?", (Path(repo).name, limit)).fetchall()
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    if not rows:
        return None
    over_words = [rounds for rounds, words, _ in rows
                  if words is not None and words > SUMMARY_WORDS]
    over_points = [rounds for rounds, _, points in rows
                   if points is not None and points > SUMMARY_POINTS]
    return (median([rounds for rounds, _, _ in rows]),
            median(over_words) if over_words else None,
            median(over_points) if over_points else None)


def rules_size(repo):
    """The bytes of `repo`'s AGENTS.md its last finished run was handed (`gitcall.rules_bytes` at
    its base, 0 where it was handed none), or None where no finished run recorded one."""
    _ensure_migrated()
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            try:
                row = connection.execute(
                    "SELECT rules_bytes FROM runs WHERE repo=? AND finished_at IS NOT NULL "
                    f"AND rules_bytes IS NOT NULL AND {REAL_WORK} "
                    "ORDER BY finished_at DESC LIMIT 1", (Path(repo).name,)).fetchone()
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    return row[0] if row else None


def ended_runs(since, until):
    """Real runs with a finish date in the inclusive range, read as plain mappings."""
    _ensure_migrated()
    try:
        with _LOCK:
            connection = _connect(readonly=True)
            connection.row_factory = sqlite3.Row
            try:
                return [dict(row) for row in connection.execute(
                    "SELECT * FROM runs WHERE finished_at >= ? AND finished_at <= ? "
                    f"AND {REAL_WORK}", (since, until))]
            finally:
                connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return []


def recent_peak_rss_mb():
    """Median measured peak of real runs finished in the last seven days, or None."""
    now = time.time()
    peaks = [peak for row in ended_runs(now - 7 * 86400, now)
             if isinstance(peak := row.get("peak_rss_mb"), (int, float))
             and math.isfinite(peak) and peak > 0]
    return median(peaks) if peaks else None


def event_paths(run_dir):
    """Kept worker event files in reporting order."""
    paths = []
    for path in Path(run_dir).glob("round-*/*/events.jsonl"):
        try:
            # Rounds are numeric; file times order retries and handovers within a round.
            order = (int(path.parent.parent.name.removeprefix("round-")),
                     path.stat().st_mtime_ns, str(path))
            paths.append((order, path))
        except (OSError, ValueError):
            continue
    return [path for _, path in sorted(paths)]


def event_tokens(path):
    """Prefer the harness's final usage over the messages it already includes."""
    def count(value):
        if not isinstance(value, dict):
            return None
        numbers = {key: number for key, number in value.items()
                   if isinstance(number, (int, float)) and not isinstance(number, bool)
                   and math.isfinite(number) and number >= 0}
        for key in ("total_tokens", "tokens"):
            if key in numbers:
                return numbers[key]
        camel = {key.lower(): number for key, number in numbers.items()}
        if "inputtokens" in camel or "outputtokens" in camel:
            return camel.get("inputtokens", 0) + camel.get("outputtokens", 0)
        keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens")
        return sum(numbers.get(key, 0) for key in keys) if any(key in numbers for key in keys) else None

    def usages(node, cumulative=False, message_id=None):
        if not isinstance(node, dict):
            return
        cumulative = cumulative or node.get("type", node.get("kind")) in (
            "result", "turn.completed", "run_terminal")
        message_id = node.get("id", message_id)
        total = count(node.get("total_token_usage"))
        if total is not None:
            yield total, True, message_id
            return
        total = count(node.get("last_token_usage"))
        if total is not None:
            yield total, True, message_id
            return
        value = count(node.get("usage"))
        if value is not None:
            yield value, cumulative, message_id
            return
        # Only usage envelopes carry counters: tool arguments and generated content can
        # contain arbitrary numbers, including examples of token counters.  A `step_update` is
        # one model call's own usage, so a stream cut off mid-turn still counts the calls it
        # finished; a `result` beside them that totals the whole conversation is not read.
        for key in ("message", "payload", "info", "stream", "record", "modelUsage", "step_update"):
            yield from usages(node.get(key), cumulative, message_id)

    final, messages = None, {}
    try:
        with Path(path).open(errors="replace") as source:
            for index, line in enumerate(source):
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                for value, cumulative, message_id in usages(event):
                    if cumulative:
                        final = value
                    else:
                        messages[index] = value
    except OSError:
        return None
    return int(final) if final is not None else int(sum(messages.values())) if messages else None


class Sampler(threading.Thread):
    """A quiet 30-second process-tree RSS sampler owned by one run loop; it checkpoints the step."""

    daemon = True

    def __init__(self, run_id, *, pid=None, log=None, interval=30):
        super().__init__(name=f"agentkit-rss-{run_id}")
        self.run_id, self.pid, self.log, self.interval = run_id, pid, log, interval
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.wait(self.interval):
            sample_rss(self.run_id, self.pid, log=self.log)
            close_step(self.run_id, keep=True, log=self.log)

    def stop(self):
        self.stop_event.set()

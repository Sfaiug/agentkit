"""Best-effort SQLite history for completed and running agentkit runs."""

import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from statistics import median

from . import config, host, record

_LOCK = threading.Lock()
SUMMARY_TASKS = 20    # the status line looks back over this many finished runs per repo
SUMMARY_WORDS = 400   # ... and contrasts tasks over this many words outside the checks block
SUMMARY_POINTS = 3    # ... and tasks over this many numbered goal points, by median rounds
# The repositories the smoke and e2e suites clone: their runs are tests, never work to learn from.
SANDBOX_REPOS = ("agentkit-smoke", "agentkit-e2e")
# The condition every statistic reads rows under: no stopped run and no suite's (`suite_run`).
# Every other row is read as it was written, never rewritten.
REAL_WORK = "COALESCE(final_state,'') != 'stopped' AND NOT suite_run(run_id, repo)"
STEP_COLUMNS = {"executor": "executor_seconds", "done-when": "done_when_seconds",
                "reviewer": "reviewer_seconds", "merge": "merge_seconds"}
# The waits a run marks, each summed across its resumes; NULL on a row written before them.
# A landing check's wait for a heavy-suite turn is the lander's, inside the run's line wait.
WAIT_COLUMNS = {"slot": "slot_wait_seconds", "suite": "suite_wait_seconds",
                "merge": "merge_wait_seconds", "lander": "lander_wait_seconds"}
_OPEN = {}     # run_id -> [step, since]: the step this process runs, counted up to `since`
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
              ("lander_wait_seconds", "REAL"), ("rules_bytes", "INTEGER"))

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


def path():
    """The history database follows the configured HOME, including test homes."""
    return config.HOME / "history.db"


def _connect(*, readonly=False):
    database = path()
    if readonly:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.create_function("suite_run", 2, suite_run)     # what REAL_WORK reads by
        return connection
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=2)
    connection.execute(SCHEMA)
    connection.execute(REVIEWS_SCHEMA)
    have = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
    for name, kind in MIGRATIONS:
        if name not in have:
            connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")
    return connection


def _write(fn, log=None):
    """Run one database mutation; history can never make a run fail."""
    try:
        with _LOCK:
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
              task_checks=None, task_files=None, orchestrator=None, log=None):
    """Create or refresh the durable row written before a run does work.

    A sandbox's run is never recorded: the row a launch wrote before its repository was known
    goes, and every later write finds no row to change.  The orchestrator is the launching
    seat's at the first write, whatever that seat runs by a resume.
    """
    if sandbox(repo):
        _write(lambda connection: connection.execute(
            "DELETE FROM runs WHERE run_id=?", (run_id,)), log)
        return
    started_at = time.time() if started_at is None else started_at
    repo = Path(repo).name if repo else None
    values = (run_id, repo, executor, reviewer, rounds_used, "running", None, started_at,
              None, 0.0, 0.0, 0.0, 0.0, None, None, None, None, session,
              task_words, task_points, task_checks, task_files, orchestrator, 0.0, 0.0, 0.0, 0.0)

    def insert(connection):
        connection.execute(
            "INSERT INTO runs (run_id, repo, executor, reviewer, rounds_used, final_state, verdict, "
            "started_at, finished_at, executor_seconds, done_when_seconds, reviewer_seconds, "
            "merge_seconds, total_seconds, executor_tokens, reviewer_tokens, peak_rss_mb, session, "
            "task_words, task_points, task_checks, task_files, orchestrator, "
            "slot_wait_seconds, suite_wait_seconds, merge_wait_seconds, lander_wait_seconds) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET repo=COALESCE(excluded.repo,runs.repo), "
            "executor=COALESCE(excluded.executor,runs.executor), reviewer=COALESCE(excluded.reviewer,runs.reviewer), "
            "rounds_used=excluded.rounds_used, final_state='running', verdict=NULL, "
            "finished_at=NULL, total_seconds=NULL, "
            "session=COALESCE(excluded.session,runs.session), "
            "task_words=COALESCE(excluded.task_words,runs.task_words), "
            "task_points=COALESCE(excluded.task_points,runs.task_points), "
            "task_checks=COALESCE(excluded.task_checks,runs.task_checks), "
            "task_files=COALESCE(excluded.task_files,runs.task_files), "
            "orchestrator=COALESCE(runs.orchestrator,excluded.orchestrator)", values)

    _write(insert, log)


def update_run(run_id, *, log=None, **fields):
    """Update known row fields, silently retaining unknown state keys."""
    _write(lambda connection: _update(connection, run_id, fields), log)


def _update(connection, run_id, fields):
    allowed = {"repo", "executor", "reviewer", "rounds_used", "final_state", "verdict",
               "started_at", "finished_at", "executor_seconds", "done_when_seconds",
               "reviewer_seconds", "merge_seconds", "total_seconds", "executor_tokens",
               "reviewer_tokens", "peak_rss_mb", "session", "task_words", "task_points",
               "task_checks", "task_files", "orchestrator", "changed_lines", "live_at",
               "rules_bytes"}
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


def add_wait(run_id, wait, seconds, *, log=None):
    """Add one finished wait to its column; a row from before the columns stays unrecorded."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return
    column = WAIT_COLUMNS[wait]
    _write(lambda connection: connection.execute(
        f"UPDATE runs SET {column}={column}+? WHERE run_id=?", (max(0.0, seconds), run_id)), log)


def add_tokens(run_id, role, tokens, *, log=None):
    """Accumulate role tokens across rounds when an event log reports them."""
    column = "executor_tokens" if role == "executor" else "reviewer_tokens" \
        if role == "reviewer" else None
    if column is None or not isinstance(tokens, (int, float)) or isinstance(tokens, bool):
        return
    _write(lambda connection: connection.execute(
        f"UPDATE runs SET {column}=COALESCE({column},0)+? WHERE run_id=?",
        (int(tokens), run_id)), log)


def record_review(run_id, review_id, *, harness, model, blocking, followup, note, log=None):
    """Keep one finished review's weighed counts, including landing reviews in the same round.

    Its output directory identifies it, so recording it again cannot count it twice; only
    runs already recorded in history can contribute.
    """
    _write(lambda connection: connection.execute(
        "INSERT INTO reviews (run_id, review_id, harness, model, blocking, followup, note) "
        "SELECT run_id, ?,?,?,?,?,? FROM runs WHERE run_id=? "
        "ON CONFLICT(run_id, review_id) DO NOTHING",
        (review_id, harness, model, blocking, followup, note, run_id)), log)


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


def open_step(run_id, step, at=None, *, log=None):
    """Count the step this process was in up to `at`, and count `step` from there."""
    at = time.time() if at is None else at
    close_step(run_id, at, log=log)
    if step in STEP_COLUMNS:
        with _OPEN_LOCK:
            _OPEN[run_id] = [step, at]


def close_step(run_id, at=None, *, keep=False, log=None):
    """Add the seconds this process's step ran since it was last counted; the step, or None.

    Only the process running a step counts it, so nobody adds the time after a loop died,
    parked or was stopped: the sampler's checkpoint (`keep`, which counts and carries on)
    already counted the dead loop's work to within its interval.  A retry closes its step for
    the wait and opens it again after.
    """
    at = time.time() if at is None else at
    with _OPEN_LOCK:
        entry = _OPEN.get(run_id) if keep else _OPEN.pop(run_id, None)
        if entry is None:
            return None
        step, since = entry
        if keep:
            entry[1] = max(since, at)
    add_seconds(run_id, step, at - since, log=log)
    return step


def finish_run(run_id, *, final_state=None, verdict=None, rounds_used=None,
               finished_at=None, started_at=None, peak_rss_mb=None,
               executor=None, reviewer=None, session=None, repo=None, task_files=None,
               changed_lines=None, rules_bytes=None, log=None):
    """Record the row's final lifecycle fields and duration in one commit.

    No reader sees an ending without the run time it closes.
    """
    finished_at = time.time() if finished_at is None else finished_at
    values = {"final_state": final_state, "verdict": verdict, "rounds_used": rounds_used,
              "finished_at": finished_at, "peak_rss_mb": peak_rss_mb,
              "executor": executor, "reviewer": reviewer, "session": session, "repo": repo,
              "task_files": task_files, "changed_lines": changed_lines,
              "rules_bytes": rules_bytes}
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
        with _LOCK:
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
    """The bytes of `repo`'s AGENTS.md its last finished run was handed (`run.rules_bytes` at
    its base), or None where no finished run recorded one."""
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

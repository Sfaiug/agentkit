// Package history opens ~/.agentkit/history.db, the record of past work Python ak keeps, through
// Go's one SQLite.  It keeps the database in Python's schema, as Python's history._connect brings
// an older one up to today's tables, holds the scoreboard's queries, and writes a run's row
// (row.go).
package history

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// The tables and columns Python ak writes, as its history module declares them, word for word:
// SQLite keeps each table's statement as it was written.
const (
	keptSchema = "CREATE TABLE IF NOT EXISTS kept (since REAL)"
	runsSchema = `
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
`
	phasesSchema = `
CREATE TABLE IF NOT EXISTS phases (
    run_id TEXT,
    phase TEXT,
    started_at REAL,
    ended_at REAL,
    PRIMARY KEY (run_id, phase, started_at)
)
`
	checksSchema = `
CREATE TABLE IF NOT EXISTS checks (
    run_id TEXT,
    round INTEGER,
    kind TEXT,
    command TEXT,
    tree TEXT,
    place TEXT,
    exit INTEGER,
    requested_at REAL,
    started_at REAL,
    finished_at REAL,
    rerun INTEGER
)
`
	testRedsSchema = `
CREATE TABLE IF NOT EXISTS test_reds (
    run_id TEXT,
    round INTEGER,
    kind TEXT,
    tree TEXT,
    test TEXT,
    flaky INTEGER,
    at REAL
)
`
	conflictsSchema = `
CREATE TABLE IF NOT EXISTS conflicts (
    run_id TEXT,
    at REAL,
    how TEXT,
    target TEXT,
    tip TEXT,
    path TEXT,
    added_only INTEGER,
    outcome TEXT
)
`
	reviewsSchema = `
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
`
	findingsSchema = `
CREATE TABLE IF NOT EXISTS findings (
    run_id TEXT,
    review_id TEXT,
    round INTEGER,
    path TEXT,
    line INTEGER,
    handed TEXT,
    kind TEXT,
    proof TEXT,
    commit_exit INTEGER,
    base_exit INTEGER,
    replayed TEXT,
    reason TEXT,
    outcome TEXT,
    at REAL
)
`
	ownerSchema = `
CREATE TABLE IF NOT EXISTS owner (
    at REAL,
    kind TEXT,
    waited REAL
)
`
	donesSchema = `
CREATE TABLE IF NOT EXISTS dones (
    conversation TEXT,
    at REAL,
    began REAL
)
`
	doneRunsSchema = `
CREATE TABLE IF NOT EXISTS done_runs (
    conversation TEXT,
    at REAL,
    run_id TEXT
)
`
	meterReadingsSchema = `
CREATE TABLE IF NOT EXISTS meter_readings (
    provider TEXT,
    account TEXT,
    meter TEXT,
    used REAL,
    resets_at REAL,
    window_secs REAL,
    at REAL,
    source TEXT,
    PRIMARY KEY (provider, account, meter, at)
)
`
	turnUsageSchema = `
CREATE TABLE IF NOT EXISTS turn_usage (
    turn TEXT,
    run_id TEXT,
    role TEXT,
    account TEXT,
    model TEXT,
    began REAL,
    at REAL,
    input INTEGER,
    cache_write INTEGER,
    cache_read INTEGER,
    output INTEGER
)
`
)

// The columns each table gained after it was first made, in the order Python adds them.
var migrations = []struct{ table, columns string }{
	{"runs", "task_words INTEGER, task_points INTEGER, task_checks INTEGER, task_files TEXT, " +
		"orchestrator TEXT, changed_lines INTEGER, live_at REAL, slot_wait_seconds REAL, " +
		"suite_wait_seconds REAL, merge_wait_seconds REAL, lander_wait_seconds REAL, " +
		"rules_bytes INTEGER, change TEXT, merge_sha TEXT, parked_at REAL, " +
		"first_review_lines INTEGER, landing_breaks INTEGER, broke_after_merge TEXT, " +
		"own_orchestrator TEXT, executor_effort TEXT, own_orchestrator_effort TEXT, kind TEXT, " +
		"counted_turns TEXT, review_pair TEXT, landing_flakes INTEGER, plan_line TEXT, " +
		"no_review INTEGER"},
	{"phases", "wait_kind TEXT"},
	{"reviews", "round INTEGER, verdict TEXT, effort TEXT"},
	{"findings", "inside_fix INTEGER"},
	{"owner", "conversation TEXT"},
	{"dones", "work TEXT"},
	{"meter_readings", "plan TEXT"},
}

// dropped are the columns of runs an older ak made and nothing reads or writes.
var dropped = []string{"suite_cpu_seconds", "suite_wall_seconds", "suite_peak_mb", "suite_repo", "merged"}

// walMax is Python's waiter.WAL_MAX: how far the WAL grows before the tick moves it into the
// database, and what a commit beginning it anew cuts its file back to.
const walMax = 4 * 1024 * 1024

// A Row is a query's row by column name, each value as SQLite holds it: int64, float64, string
// (a blob, which ak never writes, as its text) or nil.  Of two columns of one name the first is
// kept, as Python's rows read it.
type Row map[string]any

// A DB is history.db opened.
type DB struct{ conn *sqlite3.Conn }

// Path is where history.db stands.
func Path() string {
	return filepath.Join(config.Home(), "history.db")
}

// Open is history.db brought up to today's tables, keeping its rows; nil where none stands, as
// a read makes none.  An error where Go leaves it to Python ak, having written nothing: SQLite
// cannot open it, it keeps seats' tokens, which Python alone reads on, or its tokens wait for
// Python's one-time repair.  All of it under Python's writers' lock, so what Go decides on stays
// as it read it until it is done.
func Open() (*DB, error) {
	path := Path()
	if _, err := os.Stat(path); err != nil {
		return nil, nil
	}
	held, err := writers(path)
	if err != nil {
		return nil, err
	}
	defer held.Close()
	recounted, err := leftToPython(path)
	if err != nil {
		return nil, err
	}
	db, err := connect(path, sqlite3.OPEN_READWRITE)
	if err == nil {
		err = db.upgrade(recounted)
	}
	if err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// writers is Python's lock every writer of the database at path holds, waited for, Python's
// waiter.writing: one writer at a time across processes, SQLite's own wait being too short.
func writers(path string) (*os.File, error) {
	return lock.Wait(context.Background(), strings.TrimSuffix(path, ".db")+".lock")
}

// connect opens a connection that never moves the WAL into the database, which the tick alone
// does, waits on a writer as Python's does, and reads realWork's suite_run.
func connect(path string, flags sqlite3.OpenFlag) (*DB, error) {
	conn, err := sqlite.Open(path, flags)
	if err != nil {
		return nil, err
	}
	db := &DB{conn}
	if _, err = conn.Config(sqlite3.DBCONFIG_NO_CKPT_ON_CLOSE, true); err == nil {
		err = conn.BusyTimeout(2 * time.Second)
	}
	if err == nil {
		err = conn.CreateFunction("suite_run", 2, 0, func(ctx sqlite3.Context, arg ...sqlite3.Value) {
			repo := ""
			if arg[1].Type() == sqlite3.TEXT {
				repo = arg[1].Text()
			}
			ctx.ResultBool(suiteRun(arg[0].Text(), repo))
		})
	}
	if err != nil {
		conn.Close()
		return nil, err
	}
	return db, nil
}

// leftToPython is an error where the database is Python ak's alone, else whether Python's one-time
// recount of its tokens is done.  It reads through a connection that cannot write, where SQLite
// refuses a crashed writer's journal rather than rolls it back.
func leftToPython(path string) (recounted bool, err error) {
	db, err := connect(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return false, err
	}
	defer db.Close()
	seats, err := db.keepsSeats()
	if err != nil || seats {
		return false, cmp.Or(err, errors.New("it keeps seats' tokens, which Python ak alone reads on"))
	}
	return db.recounted()
}

// errOwed is a history whose tokens wait for Python's one-time recount: it reads the turns' event
// files, which only Python ak can.
var errOwed = errors.New("its tokens wait for Python ak's one-time repair")

// recounted is whether Python's one-time recount of the tokens is done, errOwed where it is owed.
func (db *DB) recounted() (bool, error) {
	version, err := db.rows("PRAGMA user_version")
	if err != nil {
		return false, err
	}
	// from 2 on, the recount is done
	if version[0]["user_version"].(int64) >= 2 {
		return true, nil
	}
	if repair, err := db.repairs(); err != nil || repair {
		return false, cmp.Or(err, errOwed)
	}
	return false, nil
}

// upgrade is Python's history._connect on a database that is not Python's alone: the connection
// made a writer, and today's tables and columns brought in in one transaction.
func (db *DB) upgrade(recounted bool) error {
	if err := db.writer(); err != nil {
		return err
	}
	return db.migrate(recounted)
}

// writer makes the connection a writer as Python's waiter.connect makes one.
func (db *DB) writer() error {
	for _, pragma := range []string{"journal_mode=WAL", "synchronous=NORMAL", "wal_autocheckpoint=0",
		fmt.Sprintf("journal_size_limit=%d", walMax)} {
		if err := db.exec("PRAGMA " + pragma); err != nil {
			return err
		}
	}
	return nil
}

// migrate makes the tables and columns the database lacks, and marks it past the tokens' repair.
func (db *DB) migrate(recounted bool) (err error) {
	tx, err := db.conn.BeginImmediate()
	if err != nil {
		return err
	}
	defer tx.End(&err)
	// read before runs is made, in the statement that writes it: dones are kept from a history's
	// start, else from the moment an older one first met them
	if err := db.exec(keptSchema); err != nil {
		return err
	}
	if err := db.exec("INSERT INTO kept (since) SELECT CASE WHEN EXISTS (SELECT 1 FROM sqlite_master "+
		"WHERE name = 'runs') THEN ? ELSE 0 END WHERE NOT EXISTS (SELECT 1 FROM kept)",
		float64(time.Now().UnixNano())/1e9); err != nil {
		return err
	}
	for _, schema := range []string{runsSchema, phasesSchema, checksSchema, testRedsSchema,
		conflictsSchema, reviewsSchema, findingsSchema, ownerSchema, donesSchema, doneRunsSchema,
		meterReadingsSchema, turnUsageSchema} {
		if err := db.exec(schema); err != nil {
			return err
		}
	}
	for _, migration := range migrations {
		have, err := db.columns(migration.table)
		if err != nil {
			return err
		}
		for _, column := range strings.Split(migration.columns, ", ") {
			if have[strings.Fields(column)[0]] {
				continue
			}
			if err := db.exec("ALTER TABLE " + migration.table + " ADD COLUMN " + column); err != nil {
				return err
			}
		}
	}
	have, err := db.columns("runs")
	for _, column := range dropped {
		if err == nil && have[column] {
			err = db.exec("ALTER TABLE runs DROP COLUMN " + column)
		}
	}
	if err != nil || recounted {
		return err
	}
	return db.exec("PRAGMA user_version=2")
}

// repairs is whether Python's one-time recount of the tokens could change a row's: some row's run
// keeps a worker's event file to count them from.
func (db *DB) repairs() (bool, error) {
	have, err := db.columns("runs")
	if err != nil || !have["executor_tokens"] || !have["reviewer_tokens"] {
		return false, err
	}
	rows, err := db.rows("SELECT run_id FROM runs")
	for _, row := range rows {
		found, bad := filepath.Glob(filepath.Join(run.Runs(), row.Text("run_id"), "round-*", "*", "events.jsonl"))
		if len(found) > 0 || bad != nil {
			return true, nil
		}
	}
	return false, err
}

// columns are the table's column names, none for a table not made yet.
func (db *DB) columns(table string) (map[string]bool, error) {
	rows, err := db.rows("PRAGMA table_info(" + table + ")")
	have := map[string]bool{}
	for _, row := range rows {
		have[row.Text("name")] = true
	}
	return have, err
}

// Close lets the database go, its WAL left for the tick to move.
func (db *DB) Close() error {
	if db == nil {
		return nil
	}
	return db.conn.Close()
}

// exec runs a statement, its ? bound to args in order.
func (db *DB) exec(statement string, args ...any) error {
	_, err := db.rows(statement, args...)
	return err
}

// rows are what the query answers, its ? bound to args in order, as Python's sqlite3 binds them:
// a record's number as the int or float Python reads, true as 1, and what it cannot bind refused.
func (db *DB) rows(query string, args ...any) ([]Row, error) {
	stmt, _, err := db.conn.Prepare(query)
	if err != nil {
		return nil, err
	}
	defer stmt.Close()
	for i, arg := range args {
		if number, ok := arg.(run.Number); ok {
			arg, _ = run.Num(number)
			if whole, err := strconv.ParseInt(string(number), 10, 64); err == nil {
				arg = whole
			}
		}
		switch arg := arg.(type) {
		case nil:
			err = stmt.BindNull(i + 1)
		case bool:
			err = stmt.BindBool(i+1, arg)
		case float64:
			err = stmt.BindFloat(i+1, arg)
		case int:
			err = stmt.BindInt(i+1, arg)
		case int64:
			err = stmt.BindInt64(i+1, arg)
		case string:
			err = stmt.BindText(i+1, arg)
		default:
			err = fmt.Errorf("Error binding parameter %d: type '%T' is not supported", i+1, arg)
		}
		if err != nil {
			return nil, err
		}
	}
	var rows []Row
	for stmt.Step() {
		row := Row{}
		for col := range stmt.ColumnCount() {
			name := stmt.ColumnName(col)
			if _, ok := row[name]; ok {
				continue
			}
			switch stmt.ColumnType(col) {
			case sqlite3.INTEGER:
				row[name] = stmt.ColumnInt64(col)
			case sqlite3.FLOAT:
				row[name] = stmt.ColumnFloat(col)
			case sqlite3.TEXT, sqlite3.BLOB:
				row[name] = stmt.ColumnText(col)
			default:
				row[name] = nil
			}
		}
		rows = append(rows, row)
	}
	return rows, stmt.Err()
}

// suiteRun is whether a row is a test suite's run, which today's ak never records and an older
// one did: its repository, or the one its run's record names, is a suite's throwaway.
func suiteRun(runID, repo string) bool {
	if sandbox(repo) {
		return true
	}
	record, _ := run.Read(filepath.Join(run.Runs(), runID))
	return record != nil && sandbox(record.Str("repo"))
}

// sandbox is whether a repository is a suite's: the agentkit-smoke the suites clone, or one
// under some HOME's .agentkit/tmp.
func sandbox(repo string) bool {
	if repo == "" {
		return false
	}
	if filepath.Base(repo) == "agentkit-smoke" {
		return true
	}
	for dir := filepath.Dir(repo); ; dir = filepath.Dir(dir) {
		if filepath.Base(dir) == "tmp" && filepath.Base(filepath.Dir(dir)) == ".agentkit" {
			return true
		}
		if dir == filepath.Dir(dir) {
			return false
		}
	}
}

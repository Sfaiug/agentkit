package history

import (
	"cmp"
	"path/filepath"

	"agentkit/internal/run"
)

// realWork is the condition every statistic reads rows under: no stopped run, none of unknown
// ending, which no statistic can read, and no suite's.
const realWork = "COALESCE(final_state,'') NOT IN ('stopped', 'unknown') AND NOT suite_run(run_id, repo)"

// The scoreboard's queries, Python's of the same name.  Each answers false, as Python's do, where
// the database cannot answer: none stands, or SQLite failed.

// EndedRuns are the real runs finished in the inclusive range.
func (db *DB) EndedRuns(since, until float64) ([]Row, bool) {
	return db.read("SELECT * FROM runs WHERE finished_at >= ? AND finished_at <= ? AND "+realWork, since, until)
}

// Checks are the check rows of the runs finished in the inclusive range, unfinished ones too.
func (db *DB) Checks(since, until float64) ([]Row, bool) {
	return db.read("SELECT checks.* FROM checks JOIN runs USING (run_id) "+
		"WHERE runs.finished_at >= ? AND runs.finished_at <= ?", since, until)
}

// Findings are the weighed rows of real runs by date, and earlier follow-ups and answered
// disputes for merged changes' counts, each with its run's row and whether an earlier blocking
// round raised the same path and proof.
func (db *DB) Findings(since, until float64) ([]Row, bool) {
	return db.read("SELECT f.*, runs.*, EXISTS (SELECT 1 FROM findings earlier "+
		"WHERE earlier.run_id=f.run_id AND earlier.path=f.path AND earlier.proof=f.proof "+
		"AND earlier.kind='finding' AND earlier.round<f.round) AS raised_again "+
		"FROM findings f JOIN runs USING (run_id) WHERE f.at <= ? AND "+
		"(f.at >= ? OR f.kind='follow-up' OR f.outcome IS NOT NULL) AND "+realWork, until, since)
}

// Conflicts are the real conflicts by date, and earlier ones on changes merged in the range.
func (db *DB) Conflicts(since, until float64) ([]Row, bool) {
	return db.read(`SELECT c.at, c.path, c.added_only, repo, COALESCE(NULLIF("change", ''), run_id) AS "change" `+
		`FROM conflicts c JOIN runs USING (run_id) WHERE c.at <= ? AND `+
		`(c.at >= ? OR (repo, COALESCE(NULLIF("change", ''), run_id)) IN (`+
		`SELECT repo, COALESCE(NULLIF("change", ''), run_id) FROM runs `+
		`WHERE finished_at >= ? AND finished_at <= ? AND changed_lines IS NOT NULL)) AND `+realWork,
		until, since, since, until)
}

// Parks are the moments runs were parked in the inclusive range: stopped rows, which realWork
// leaves out of every other count.
func (db *DB) Parks(since, until float64) ([]Row, bool) {
	return db.read("SELECT parked_at FROM runs WHERE parked_at >= ? AND parked_at <= ?", since, until)
}

// Owner are the moments of the owner's time in the inclusive range.
func (db *DB) Owner(since, until float64) ([]Row, bool) {
	return db.read("SELECT at, kind, waited FROM owner WHERE at >= ? AND at <= ?", since, until)
}

// Dones are the dones in the inclusive range: `live` once each of its runs ended and each that
// passed is live, the last of them, NULL while one runs, where one passed without going live, a
// run has no row, or none passed; `answered` the conversation's answered waits between its
// first message and its done.
func (db *DB) Dones(since, until float64) ([]Row, bool) {
	return db.read("SELECT at, began, (SELECT CASE WHEN SUM(runs.finished_at IS NULL) "+
		"OR SUM(runs.final_state = 'pass' AND runs.live_at IS NULL) THEN NULL "+
		"ELSE MAX(CASE WHEN runs.final_state = 'pass' THEN runs.live_at END) END "+
		"FROM done_runs LEFT JOIN runs USING (run_id) "+
		"WHERE done_runs.conversation = dones.conversation AND done_runs.at = dones.at) AS live, "+
		"(SELECT COALESCE(SUM(waited), 0) FROM owner WHERE kind = 'answered' "+
		"AND owner.conversation = dones.conversation "+
		"AND owner.at >= dones.began AND owner.at <= dones.at) AS answered "+
		"FROM dones WHERE at >= ? AND at <= ?", since, until)
}

// SeatUsage is what the seats spent in the inclusive range, by project, as Python's
// seat_tokens.read returns it once the seats' files are read (SeatTokens): none where no seat
// ever had a table made.
func (db *DB) SeatUsage(since, until float64) ([]Row, bool) {
	return db.read("SELECT repo, at, tokens FROM seat_usage WHERE at >= ? AND at <= ?", since, until)
}

// Phases are a run's phases in order, the one under way ending at its last checkpoint.
func (db *DB) Phases(runID string) ([]Row, bool) {
	return db.read("SELECT phase, started_at, ended_at FROM phases WHERE run_id=? ORDER BY started_at, phase", runID)
}

// FinishedRepos are the repositories with a real run finished, by name.
func (db *DB) FinishedRepos() ([]Row, bool) {
	return db.read("SELECT DISTINCT repo FROM runs WHERE finished_at IS NOT NULL AND repo IS NOT NULL AND " +
		realWork + " ORDER BY repo")
}

// Sized are the rounds, words and points of the repository's last finished tasks, newest first.
func (db *DB) Sized(repo string, limit int) ([]Row, bool) {
	return db.read("SELECT rounds_used, task_words, task_points FROM runs "+
		"WHERE repo=? AND finished_at IS NOT NULL AND rounds_used IS NOT NULL AND (kind='task' OR kind IS NULL) AND "+
		realWork+" ORDER BY finished_at DESC LIMIT ?", filepath.Base(repo), limit)
}

// RulesBytes is the size of the AGENTS.md the repository's last finished run recorded being
// handed, none where no finished run recorded one.
func (db *DB) RulesBytes(repo string) ([]Row, bool) {
	return db.read("SELECT rules_bytes FROM runs WHERE repo=? AND finished_at IS NOT NULL AND rules_bytes IS NOT NULL AND "+
		realWork+" ORDER BY finished_at DESC LIMIT 1", filepath.Base(repo))
}

// read is rows, false where no database stands or SQLite failed.
func (db *DB) read(query string, args ...any) ([]Row, bool) {
	if db == nil {
		return nil, false
	}
	rows, err := db.rows(query, args...)
	return rows, err == nil
}

// Merged is whether the row's run merged: its size survives run cleanup, an older merge needs
// its record.
func (row Row) Merged() bool {
	if row["changed_lines"] != nil {
		return true
	}
	record, _ := run.Read(filepath.Join(run.Runs(), row.Text("run_id")))
	return record != nil && record.Truthy("merged")
}

// Change is the change the row's run belongs to: the one it continues, else its own.
func (row Row) Change() string {
	return cmp.Or(row.Text("change"), row.Text("run_id"))
}

// Num is the column's number, false for none.
func (row Row) Num(column string) (float64, bool) {
	switch value := row[column].(type) {
	case int64:
		return float64(value), true
	case float64:
		return value, true
	}
	return 0, false
}

// Text is the column's text, "" for none.
func (row Row) Text(column string) string {
	value, _ := row[column].(string)
	return value
}

// Truthy is whether Python reads the column's value as true.
func (row Row) Truthy(column string) bool {
	switch value := row[column].(type) {
	case nil:
		return false
	case int64:
		return value != 0
	case float64:
		return value != 0
	case string:
		return value != ""
	}
	return true
}

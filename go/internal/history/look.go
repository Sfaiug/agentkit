package history

import (
	"os"

	"github.com/ncruces/go-sqlite3"
)

// Look is history.db through a connection that cannot write, as Python's readers open it: nil,
// which answers nothing, where none stands or SQLite cannot open it.
func Look() *DB {
	// where none stands, SQLite is not even compiled
	if _, err := os.Stat(Path()); err != nil {
		return nil
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return nil
	}
	return db
}

// Select is what the query finds, nothing where the database cannot answer, as before a table is
// made, Python's spend._select.
func (db *DB) Select(query string, args ...any) []Row {
	rows, _ := db.read(query, args...)
	return rows
}

// ReviewedRuns are, per effort the identity reviewed at, the runs it finished a review of that are
// real work, a review from before its round was recorded counting for nothing, Python's
// history.reviewed_runs.
func (db *DB) ReviewedRuns(harness, model string) ([]Row, bool) {
	return db.read("SELECT reviews.effort, COUNT(DISTINCT run_id), "+
		"COUNT(DISTINCT CASE WHEN reviews.round=1 AND reviews.verdict='PASS' THEN run_id END) "+
		"FROM reviews JOIN runs USING (run_id) WHERE harness=? AND model=? AND reviews.round IS NOT NULL AND "+
		realWork+" GROUP BY reviews.effort", harness, model)
}

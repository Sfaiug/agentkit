package history

import (
	"os"
	"strings"

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
// history.reviewed_runs, which reads once its migration has brought the tables up to today's.
func (db *DB) ReviewedRuns(harness, model string) ([]Row, bool) {
	if db == nil {
		return nil, false
	}
	return db.read("SELECT reviews.effort, COUNT(DISTINCT run_id), "+
		"COUNT(DISTINCT CASE WHEN reviews.round=1 AND reviews.verdict='PASS' THEN run_id END) "+
		"FROM "+db.migrated("reviews")+" JOIN runs USING (run_id) WHERE harness=? AND model=? AND "+
		"reviews.round IS NOT NULL AND "+realWork+" GROUP BY reviews.effort", harness, model)
}

// migrated is table as Python's migration leaves it, for a connection that writes nothing: each
// column the migration would add, and the table lacks, read as the NULL it would hold.
func (db *DB) migrated(table string) string {
	have, err := db.columns(table)
	if err != nil || len(have) == 0 {
		return table
	}
	var added []string
	for _, migration := range migrations {
		if migration.table != table {
			continue
		}
		for _, column := range strings.Split(migration.columns, ", ") {
			if name := strings.Fields(column)[0]; !have[name] {
				added = append(added, "NULL AS "+name)
			}
		}
	}
	if len(added) == 0 {
		return table
	}
	return "(SELECT *, " + strings.Join(added, ", ") + " FROM " + table + ") AS " + table
}

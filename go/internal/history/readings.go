package history

import (
	"strings"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

const readingsKeptFor = 35 * 86400 // seconds a meter reading is kept: five weeks (READINGS_KEPT_FOR)

// Bare is whether history.db holds no row of what Go leaves to Python: none stands
// (run.Historyless), or one holding only meter readings, which a probe makes in a home with none
// and Go keeps as Python does.  False where SQLite cannot say.
func Bare() bool {
	if run.Historyless() {
		return true
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return false
	}
	defer db.Close()
	tables, err := db.rows("SELECT name FROM sqlite_master WHERE type = 'table' " +
		"AND name NOT IN ('kept', 'meter_readings') AND name NOT LIKE 'sqlite_%'")
	for _, table := range tables {
		held, failed := db.rows(`SELECT 1 FROM "` + strings.ReplaceAll(table.Text("name"), `"`, `""`) + `" LIMIT 1`)
		if failed != nil || len(held) > 0 {
			return false
		}
	}
	return err == nil
}

// Owed is whether history.db stands with its tokens waiting for Python's one-time repair, before
// which Go writes no row, so a fresh reading Go took would never be kept; true where SQLite cannot
// say.
func Owed() bool {
	if run.Historyless() {
		return false
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return true
	}
	defer db.Close()
	_, err = db.recounted()
	return err != nil
}

// KeepReadings is Python's history.keep_readings: meter_readings rows added, each its values in
// the columns' order (provider, account, meter, used, resets_at, window_secs, at, source, plan),
// one kept already adding nothing, and the rows past five weeks dropped once one went in.  What
// goes wrong is said in history.log, as Python's.
func KeepReadings(rows [][]any) {
	if len(rows) == 0 {
		return
	}
	apply(nil, func(db *DB) error {
		added := false
		for _, row := range rows {
			err := db.exec("INSERT OR IGNORE INTO meter_readings (provider, account, meter, used, resets_at, "+
				"window_secs, at, source, plan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row...)
			if err != nil {
				return err
			}
			added = added || db.conn.Changes() > 0
		}
		if !added {
			return nil
		}
		return db.exec("DELETE FROM meter_readings WHERE at < ?", now()-readingsKeptFor)
	})
}

package history

import (
	"errors"
	"io/fs"
	"os"
	"strings"
)

// A Source is a file a seat's harness keeps the tokens it spends in, as seat_sources keeps it:
// its path, that harness, the seat's project and the login it runs on.
type Source struct{ Path, Harness, Repo, Account string }

// seatTables is Python's seat_tokens.TABLES: each table, then its columns in order, a table made
// before a column was added getting it at its end.
var seatTables = [][]string{
	{"seat_sources", "path TEXT PRIMARY KEY", "harness TEXT", "repo TEXT", "cursor TEXT", "account TEXT"},
	{"seat_usage", "event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "tokens INTEGER", "account TEXT", "model TEXT",
		"input INTEGER", "cache_write INTEGER", "cache_read INTEGER", "output INTEGER"},
}

// errToRead takes back a write that found a source holding lines to count.
var errToRead = errors.New("a seat's source holds lines to read")

// Sources is Python's seat_tokens.read where no source has anything to read yet: the seats' tables
// made or brought up to today's columns, and each source kept, to be read from its start.  False,
// having written nothing, where a source kept or given holds a file, whose lines Python counts, or
// the write fails, which Python says.
func Sources(sources []Source) bool {
	return commit(func(db *DB) error {
		for _, table := range seatTables {
			if err := db.exec("CREATE TABLE IF NOT EXISTS " + table[0] + " (" + strings.Join(table[1:], ", ") + ")"); err != nil {
				return err
			}
			have, err := db.columns(table[0])
			for _, column := range table[1:] {
				if name, _, _ := strings.Cut(column, " "); err == nil && !have[name] {
					err = db.exec("ALTER TABLE " + table[0] + " ADD COLUMN " + column)
				}
			}
			if err != nil {
				return err
			}
		}
		if err := db.exec("CREATE INDEX IF NOT EXISTS seat_usage_at ON seat_usage(at)"); err != nil {
			return err
		}
		for _, source := range sources {
			if err := db.exec("INSERT INTO seat_sources VALUES (?, ?, ?, '{}', ?) ON CONFLICT(path) "+
				"DO UPDATE SET repo = excluded.repo, account = excluded.account",
				source.Path, source.Harness, name(source.Repo), source.Account); err != nil {
				return err
			}
		}
		kept, err := db.rows("SELECT path FROM seat_sources")
		for _, row := range kept {
			if _, missing := os.Stat(row.Text("path")); !errors.Is(missing, fs.ErrNotExist) {
				return errToRead // Python's reader opens whatever stands there
			}
		}
		return err
	}) == nil
}

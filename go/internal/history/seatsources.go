package history

import (
	"errors"
	"io/fs"
	"os"
	"slices"
	"strings"
)

// A Source is a file a seat's harness keeps the tokens it spends in, as seat_sources keeps it:
// its path, that harness, the seat's project and the login it runs on; and the seat.
type Source struct{ Path, Harness, Repo, Account, Seat string }

// seatTables is Python's seat_tokens.TABLES: each table, then its columns in order, a table made
// before a column was added getting it at its end.
var seatTables = [][]string{
	{"seat_sources", "path TEXT PRIMARY KEY", "harness TEXT", "repo TEXT", "cursor TEXT", "account TEXT"},
	{"seat_usage", "event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "tokens INTEGER", "account TEXT", "model TEXT",
		"input INTEGER", "cache_write INTEGER", "cache_read INTEGER", "output INTEGER"},
}

// Sources is Python's seat_tokens.read where no source has anything to read yet: the seats' tables
// made or brought up to today's columns, and each source kept, to be read from its start; and the
// seats whose files then do not open, each named with the harness seat_sources keeps for its file,
// sorted, as Python's read names them.  False, having written nothing, where a source kept or given
// holds a file, whose lines Python counts, or the write fails, which Python says.  A file that
// appears once this has looked is read from its start all the same.
func Sources(sources []Source) ([]string, bool) {
	kept := map[string]string{} // each file's harness, as its first write keeps it
	db := Look()
	for _, row := range db.Select("SELECT path, harness FROM seat_sources") {
		kept[row.Text("path")] = row.Text("harness")
	}
	db.Close()
	owners := map[string]string{}
	for _, source := range sources {
		owners[source.Path] = source.Seat
		if _, found := kept[source.Path]; !found {
			kept[source.Path] = source.Harness
		}
	}
	var uncounted []string
	for path, harness := range kept {
		if _, err := os.Stat(path); !errors.Is(err, fs.ErrNotExist) {
			return nil, false // Python's reader opens whatever stands there
		}
		if owner, found := owners[path]; found {
			uncounted = append(uncounted, owner+" ("+harness+")")
		}
	}
	slices.Sort(uncounted)
	return slices.Compact(uncounted), commit(func(db *DB) error {
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
		return nil
	}) == nil
}

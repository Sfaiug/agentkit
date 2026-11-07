package history

import (
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// seatTables are the tables what seats spend is kept in, each its columns in order, as Python's
// seat_tokens.TABLES declares them: a table made before a column was added gets it at its end.  A
// usage row's account is the login of the seat that owned its file when the tick read it; its
// model and counts by type are NULL where its harness does not tell them.
var seatTables = []struct {
	name    string
	columns []string
}{
	{"seat_sources", []string{"path TEXT PRIMARY KEY", "harness TEXT", "repo TEXT", "cursor TEXT", "account TEXT"}},
	{"seat_usage", []string{"event TEXT PRIMARY KEY", "repo TEXT", "at REAL", "tokens INTEGER", "account TEXT",
		"model TEXT", "input INTEGER", "cache_write INTEGER", "cache_read INTEGER", "output INTEGER"}},
}

// errUntold is a source Go cannot tell from another file as Python does here.
var errUntold = errors.New("a file Go cannot tell as Python does")

// SeatTokens is the tick's seat tokens row, Python's seat_tokens.read: the files each seat's harness
// keeps what it spends in become sources, known from then on whatever becomes of the seat, and each
// source is read on from its cursor, each line its harness counts a row of seat_usage once by its
// event, a row seen again keeping its larger count; the rows and the cursors they were read to in
// one commit, so a retry counts nothing twice.  A home with no seat and no sources gets no tables.
// False, having written nothing, where Python ak's is to do: a record Go cannot read as Python
// does, a source it cannot tell, or tokens waiting for Python's one-time repair.
func SeatTokens() bool {
	type source struct {
		path, harness string
		repo, account any
	}
	var sources []source
	seated := false
	for _, path := range config.SeatFiles() {
		record, err := run.ReadJSON(path)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return false
		}
		if record == nil || record.Has(config.Renamed) {
			continue
		}
		seated = true
		model, _ := config.ModelNamed(record.Str("orchestrator"))
		paths := harness.TokenSources(model.Harness, record)
		repo, account := any(""), record.Get("account")
		if record.Truthy("repo") {
			repo = name(record.Get("repo"))
		}
		if !record.Truthy("account") {
			account = config.DefaultAccount
		}
		for _, each := range paths {
			sources = append(sources, source{config.Resolve(each), model.Harness, repo, account})
		}
	}
	if !seated && !keepsSources() {
		return true
	}
	err := commit(func(db *DB) error {
		for _, table := range seatTables {
			if err := db.exec("CREATE TABLE IF NOT EXISTS " + table.name + " (" + strings.Join(table.columns, ", ") + ")"); err != nil {
				return err
			}
			have, err := db.columns(table.name)
			for _, column := range table.columns {
				if err == nil && !have[strings.Fields(column)[0]] {
					err = db.exec("ALTER TABLE " + table.name + " ADD COLUMN " + column)
				}
			}
			if err != nil {
				return err
			}
		}
		if err := db.exec("CREATE INDEX IF NOT EXISTS seat_usage_at ON seat_usage(at)"); err != nil {
			return err
		}
		for _, each := range sources {
			if err := db.exec("INSERT INTO seat_sources VALUES (?, ?, ?, '{}', ?) ON CONFLICT(path) "+
				"DO UPDATE SET repo = excluded.repo, account = excluded.account", each.path, each.harness, each.repo, each.account); err != nil {
				return err
			}
		}
		// known sources are read on after a clear, rename, harness change or seat removal
		known, err := db.rows("SELECT * FROM seat_sources")
		if err != nil {
			return err
		}
		for _, row := range known {
			path, own := row.Text("path"), row.Text("harness")
			saved, _ := run.DecodeShown([]byte(row.Text("cursor")))
			cursor, _ := saved.(*run.Object)
			if cursor == nil {
				return fmt.Errorf("no cursor for %s", path)
			}
			spends, told, err := harness.Spends(own, path, cursor)
			if !told {
				return errUntold
			}
			if err != nil {
				continue // gone, or not yet written
			}
			for _, spend := range spends {
				event := spend.Event
				if event == "" {
					event = path + ":" + strconv.FormatInt(spend.Start, 10)
				}
				counts := []any{nil, nil, nil, nil}
				for i, count := range spend.Counts {
					counts[i] = count
				}
				// a repeat counting more replaces all its line set, so the counts, model and login
				// stay those of the line that set the tokens
				if err := db.exec("INSERT INTO seat_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "+
					"ON CONFLICT(event) DO UPDATE SET tokens = excluded.tokens, "+
					"account = excluded.account, model = excluded.model, "+
					"input = excluded.input, cache_write = excluded.cache_write, "+
					"cache_read = excluded.cache_read, output = excluded.output "+
					"WHERE excluded.tokens > tokens",
					append([]any{own + ":" + event, row["repo"], spend.At, spend.Tokens, row["account"], spend.Model}, counts...)...); err != nil {
					return err
				}
			}
			if err := db.exec("UPDATE seat_sources SET cursor = ? WHERE path = ?", run.Line(cursor), path); err != nil {
				return err
			}
		}
		return nil
	})
	if errors.Is(err, errUntold) || errors.Is(err, errRepair) {
		return false
	}
	warn(nil, err)
	return true
}

// keepsSources is whether history.db keeps seats' sources, as Python's read asks where no seat
// is: false where SQLite cannot say.
func keepsSources() bool {
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return false
	}
	defer db.Close()
	seats, err := db.keepsSeats()
	return err == nil && seats
}

package history

import (
	"os"
	"path/filepath"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

// A Conflicted is a file handed to a conflict fixer, with git's classification of it: added-only
// where every conflict in it has an empty base, Python's conflict_added_only.
type Conflicted struct {
	Path      string
	AddedOnly bool
}

// Conflicts are history.db's rows of one conflicted rebase or merge, Python's history.conflicts: one
// per file as it is handed to a fixer, and the outcome its fixer rounds end with, NULL until then.
// A run Python keeps no row for keeps none here.  A write that fails is its caller's to say, never
// the run's failure.
type Conflicts struct {
	run, how, target, tip string
	rows                  []int
}

// NewConflicts are the rows of the run's integration, the way how says, of the target pinned at tip.
func NewConflicts(runID, how, target, tip string) *Conflicts {
	return &Conflicts{run: runID, how: how, target: target, tip: tip}
}

// Add keeps a row for each file handed to a fixer now, all of one moment.
func (c *Conflicts) Add(files []Conflicted) error {
	if len(files) == 0 || !recorded(c.run) {
		return nil
	}
	at := float64(time.Now().UnixNano()) / 1e9
	var added []int
	err := commit(func(db *DB) error {
		for _, file := range files {
			only := 0
			if file.AddedOnly {
				only = 1
			}
			if err := db.exec("INSERT INTO conflicts (run_id, at, how, target, tip, path, added_only) VALUES (?, ?, ?, ?, ?, ?, ?)",
				c.run, at, c.how, c.target, c.tip, file.Path, only); err != nil {
				return err
			}
			added = append(added, int(db.conn.LastInsertRowID()))
		}
		return nil
	})
	if err == nil {
		c.rows = append(c.rows, added...)
	}
	return err
}

// End writes the outcome on every row: resolved where the rounds left the branch carrying the tip.
func (c *Conflicts) End(resolved bool) error {
	if len(c.rows) == 0 {
		return nil
	}
	outcome := "aborted"
	if resolved {
		outcome = "resolved"
	}
	return commit(func(db *DB) error {
		for _, row := range c.rows {
			if err := db.exec("UPDATE conflicts SET outcome=? WHERE rowid=?", outcome, row); err != nil {
				return err
			}
		}
		return nil
	})
}

// recorded is whether Python keeps a history row for the run, which its other rows join: none for a
// suite's, launched under the suites' notify sink, nor for one in a sandbox's repository, as
// Python's history_start and start_run leave them out.
func recorded(runID string) bool {
	record, _ := run.Read(filepath.Join(run.Runs(), runID))
	return record != nil && !record.Truthy("notify_sink") && !sandbox(record.Str("repo"))
}

// Runless is whether no history of runs stands: no history.db, or one holding no run's row, as one
// Go's conflict rows made does.  A run there joins no record Python keeps of others, so Go, which
// writes no run's row yet, carries it as where none stands.
func Runless() bool {
	if run.Historyless() {
		return true
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return false
	}
	defer db.Close()
	rows, err := db.rows("SELECT 1 FROM runs LIMIT 1")
	return err == nil && len(rows) == 0
}

// commit is one change to history.db in one transaction, under the writers' lock held to its end,
// Python's _write: a database none stands for is made, and any brought up to today's tables first.
// An error, having written nothing, where SQLite failed or the tokens wait for Python's repair.
func commit(change func(*DB) error) (err error) {
	path := Path()
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return err
	}
	held, err := writers(path)
	if err != nil {
		return err
	}
	defer held.Close()
	db, err := connect(path, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		return err
	}
	defer db.Close()
	recounted, err := db.recounted()
	if err == nil {
		err = db.upgrade(recounted)
	}
	if err != nil {
		return err
	}
	tx, err := db.conn.BeginImmediate()
	if err != nil {
		return err
	}
	defer tx.End(&err)
	return change(db)
}

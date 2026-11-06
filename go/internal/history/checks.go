package history

import "os"

// A Checked is what the rows of one check name beside its command, Python's `checked`: its run,
// round and kind (`done-when`, `rules`, `base-proof`, `replay`), and the commit it checks, "" for
// a scratch run's one workspace.  A nil one leaves no row.
type Checked struct {
	Run   string
	Round int
	Kind  string
	Tree  string
}

// Check is Python's history.check: the row of one check, written as it starts, so a check that
// never returns keeps one; what it returns writes how it ended, its exit or nil where it never
// returned, and when.  asked is when it was asked for, place the helper it runs on, this host for
// "", and a command that, or a list holding it, already ran on the tree in the run is a re-run.  A
// run Python keeps no row for keeps none here, and what fails is said on log, never the check's.
func Check(checked *Checked, command string, asked float64, place string, log func(string)) (end func(exit *int)) {
	row := started(checked, command, asked, now(), place, log)
	return func(exit *int) { ended(row, exit, log) }
}

// Ran is Check for a check that may prove another program's to carry out once it ended: its row,
// started now, is written only by what it returns, so one handed on leaves none.
func Ran(checked *Checked, command string, asked float64, place string, log func(string)) (keep func(exit *int)) {
	at := now()
	return func(exit *int) { ended(started(checked, command, asked, at, place, log), exit, log) }
}

// started writes a check's row as it started at at, and names it, 0 for none: a start that did
// not commit names none, as a later check may take its id.
func started(checked *Checked, command string, asked, at float64, place string, log func(string)) int64 {
	if checked == nil || !recorded(checked.Run) {
		return 0
	}
	if place == "" {
		place, _ = os.Hostname()
	}
	var row int64
	if !apply(log, func(db *DB) error {
		err := db.exec("INSERT INTO checks (run_id, round, kind, tree, command, place, requested_at, started_at, rerun) "+
			"SELECT run_id, ?2, ?3, ?4, ?5, ?6, ?7, ?8, EXISTS (SELECT 1 FROM checks WHERE run_id=?1 AND tree IS ?4 AND "+
			"instr(char(10) || command || char(10), char(10) || ?5 || char(10))) FROM runs WHERE run_id=?1",
			checked.Run, checked.Round, checked.Kind, checked.tree(), command, place, asked, at)
		if err == nil && db.conn.Changes() > 0 {
			row = db.conn.LastInsertRowID()
		}
		return err
	}) {
		return 0
	}
	return row
}

// ended writes how the check of row ended, and when.
func ended(row int64, exit *int, log func(string)) {
	if row == 0 {
		return
	}
	var code any
	if exit != nil {
		code = *exit
	}
	apply(log, func(db *DB) error {
		return db.exec("UPDATE checks SET exit=?, finished_at=? WHERE rowid=?", code, now(), row)
	})
}

// TestReds is Python's history.test_reds: the tests a suite named once its retries ended, kept
// under its check: those confirmed red, and those that failed, then passed.
func TestReds(checked *Checked, confirmed, flaky []string, log func(string)) {
	if checked == nil || len(confirmed)+len(flaky) == 0 || !recorded(checked.Run) {
		return
	}
	at := now()
	apply(log, func(db *DB) error {
		kept := map[[2]any]bool{}
		for flake, tests := range [][]string{confirmed, flaky} {
			for _, test := range tests {
				if key := [2]any{test, flake}; !kept[key] {
					kept[key] = true
					if err := db.exec("INSERT INTO test_reds (run_id, round, kind, tree, test, flaky, at) "+
						"SELECT run_id, ?, ?, ?, ?, ?, ? FROM runs WHERE run_id=?",
						checked.Round, checked.Kind, checked.tree(), test, flake, at, checked.Run); err != nil {
						return err
					}
				}
			}
		}
		return nil
	})
}

// tree is the commit as a row holds it, NULL for a workspace.
func (c *Checked) tree() any {
	if c.Tree == "" {
		return nil
	}
	return c.Tree
}

package history

import "os"

// A Checked is what the rows of one check name beside its command, Python's `checked`: its run,
// round, an int, nil for a lander's check, which runs in none, and kind (`done-when`, `rules`,
// `base-proof`, `replay`, `landing`, `tip`), and the commit it checks, "" for a scratch run's one
// workspace.  A nil one leaves no row.
type Checked struct {
	Run   string
	Round any
	Kind  string
	Tree  string
}

// Check is Python's history.check: the row of one check, written as it starts, so a check that
// never returns keeps one; its End writes how it ended.  asked is when it was asked for, place the
// helper it runs on, this host for "", and a command that, or a list holding it, already ran on the
// tree in the run is a re-run.  A run Python keeps no row for keeps none here, and what fails is
// said on log, never the check's.
func Check(checked *Checked, command string, asked float64, place string, log func(string)) *Checking {
	return &Checking{started(checked, command, asked, place, log), log}
}

// A Checking is one check's row as Check wrote it, id 0 for none: a start that did not commit names
// none, as a later check may take its id.
type Checking struct {
	id  int64
	log func(string)
}

// End writes how the check ended, its exit or nil where it never returned, and when.
func (r *Checking) End(exit *int) {
	var code any
	if exit != nil {
		code = *exit
	}
	r.change("UPDATE checks SET exit=?, finished_at=? WHERE rowid=?", code, now())
}

// Drop takes the row back, for a check handed on to Python: it runs the check again and records
// it then.
func (r *Checking) Drop() {
	r.change("DELETE FROM checks WHERE rowid=?")
}

// change is statement on the row, its id the last value.
func (r *Checking) change(statement string, values ...any) {
	if r.id != 0 {
		apply(r.log, func(db *DB) error { return db.exec(statement, append(values, r.id)...) })
	}
}

// started writes a check's row as it starts, and names it.
func started(checked *Checked, command string, asked float64, place string, log func(string)) int64 {
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
			checked.Run, checked.Round, checked.Kind, checked.tree(), command, place, asked, now())
		if err == nil && db.conn.Changes() > 0 {
			row = db.conn.LastInsertRowID()
		}
		return err
	}) {
		return 0
	}
	return row
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

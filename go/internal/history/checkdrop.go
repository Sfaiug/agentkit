package history

// written is a row of table written under a Checked.
type written struct {
	table string
	id    int64
}

// wrote keeps the rows of table, committed, as written under the check.
func (c *Checked) wrote(table string, ids ...int64) {
	c.held.Lock()
	defer c.held.Unlock()
	for _, id := range ids {
		if id != 0 {
			c.written = append(c.written, written{table, id})
		}
	}
}

// Drop takes back every row written under the check, for one handed on to Python: it runs the
// check again and records it then.  A row is taken only while it is still the check's, as SQLite
// may give a dropped row's id to the next row of any run.
func (c *Checked) Drop(log func(string)) {
	if c == nil {
		return
	}
	c.held.Lock()
	rows := c.written
	c.written = nil
	c.held.Unlock()
	if len(rows) == 0 {
		return
	}
	apply(log, func(db *DB) error {
		for _, row := range rows {
			if err := db.exec("DELETE FROM "+row.table+" WHERE rowid=? AND run_id=? AND kind=? AND tree IS ?",
				row.id, c.Run, c.Kind, c.tree()); err != nil {
				return err
			}
		}
		return nil
	})
}

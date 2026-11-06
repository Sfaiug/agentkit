package history

// LastDone is Python's history.last_done: that conversation's last done ("last", none before its
// first) and that done's work ("work"), and since when dones are kept ("since"), the database
// brought up to today's tables first.  An error where SQLite or the tokens' repair, which is
// Python's, stands in the way.
func LastDone(conversation string) (Row, error) {
	var last Row
	err := commit(func(db *DB) error {
		rows, err := db.rows("SELECT (SELECT MAX(at) FROM dones WHERE conversation = ?) AS last, "+
			"(SELECT since FROM kept) AS since, "+
			"(SELECT work FROM dones WHERE conversation = ? ORDER BY at DESC LIMIT 1) AS work",
			conversation, conversation)
		if err == nil {
			last = rows[0]
		}
		return err
	})
	return last, err
}

// Done is Python's history.done: a seat's done in that conversation at that moment, the owner's
// first message since its previous one (nil for none known), the runs the seat started in between
// and its finished work, in one commit.  What goes wrong is said in history.log, as Python's.
func Done(conversation string, at float64, began any, runs []string, work string) {
	apply(nil, func(db *DB) error {
		err := db.exec("INSERT INTO dones (conversation, at, began, work) VALUES (?, ?, ?, ?)",
			conversation, at, began, work)
		for _, id := range runs {
			if err == nil {
				err = db.exec("INSERT INTO done_runs (conversation, at, run_id) VALUES (?, ?, ?)", conversation, at, id)
			}
		}
		return err
	})
}

package history

// Update is Python's history.update_run: the run's row given each column's value after it, a write
// that fails said on log.
func Update(id string, log func(string), pairs ...any) {
	apply(log, func(db *DB) error { return db.update(id, pairs...) })
}

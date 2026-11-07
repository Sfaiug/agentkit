package history

// Followed is the history.update_run of Python's after_merge_health and live_passed, made on each
// tick that follows the merge: the run's row keeps its merge commit, and when it went live, nil
// while it has not.
func Followed(id, sha string, live any, log func(string)) {
	pairs := []any{"merge_sha", sha}
	if live != nil {
		pairs = append(pairs, "live_at", live)
	}
	apply(log, func(db *DB) error { return db.update(id, pairs...) })
}

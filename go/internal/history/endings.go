package history

// RoundEndings is how finished runs ended, Python's history.round_endings, for the Limits page:
// of the runs realWork counts that finished, from the first carrying changed_lines on (before it
// no row tells a merge), each that merged in a round or failed, in start order.  Each row is its
// started_at, its finished_at and its round: the one its rounds_used names for a merge, 0 with
// review off, nil for a fail.  None where no counted run carries changed_lines or the database
// cannot answer.  It reads runs as it stands, through a connection that cannot write, as Python
// does, so a table lacking a column it reads answers none.
func RoundEndings() []Row {
	db := Look()
	defer db.Close()
	// realWork last: it reads a run's record, which the columns spare most rows
	counted := "finished_at IS NOT NULL AND " + realWork
	rows, ok := db.read("SELECT started_at, finished_at, " +
		"CASE WHEN changed_lines IS NOT NULL THEN rounds_used END AS round FROM runs " +
		"WHERE (changed_lines IS NOT NULL AND rounds_used IS NOT NULL " +
		"OR changed_lines IS NULL AND final_state = 'fail') AND started_at >= " +
		"(SELECT MIN(started_at) FROM runs WHERE changed_lines IS NOT NULL AND " + counted + ") AND " +
		counted + " ORDER BY started_at")
	// a read that fails part way answers none, as Python's fetchall does
	if !ok {
		return nil
	}
	return rows
}

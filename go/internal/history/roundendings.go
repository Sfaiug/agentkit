package history

// A RoundEnding is how a run ended, for `Limits` (menu.rounds_chart): when it started and
// finished, in seconds since the epoch, and whether it merged, in Round, 0 with review off.
type RoundEnding struct {
	Started, Finished float64
	Merged            bool
	Round             int
}

// RoundEndings is Python's history.round_endings: of the runs realWork counts that finished, from
// the first carrying changed_lines on -- before it no row tells a merge -- each merged in a round
// or failed, as they started.  None where none carries changed_lines or the database cannot answer.
func RoundEndings() []RoundEnding {
	db := Look()
	if db == nil {
		return nil
	}
	defer db.Close()
	// realWork last: it reads a run's record, which the columns spare most rows
	counted := "finished_at IS NOT NULL AND " + realWork
	var endings []RoundEnding
	for _, row := range db.Select("SELECT started_at, finished_at, " +
		"CASE WHEN changed_lines IS NOT NULL THEN rounds_used END AS round FROM runs " +
		"WHERE (changed_lines IS NOT NULL AND rounds_used IS NOT NULL " +
		"OR changed_lines IS NULL AND final_state = 'fail') AND started_at >= " +
		"(SELECT MIN(started_at) FROM runs WHERE changed_lines IS NOT NULL " +
		"AND " + counted + ") AND " + counted + " ORDER BY started_at") {
		started, _ := row.Num("started_at")
		finished, _ := row.Num("finished_at")
		round, merged := row.Num("round")
		endings = append(endings, RoundEnding{started, finished, merged, int(round)})
	}
	return endings
}

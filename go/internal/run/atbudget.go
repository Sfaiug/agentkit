package run

// AtBudget is whether the run is a FAIL that ran out of rounds rather than out of work, Python's
// failed_at_budget: more rounds, asked for with `ak run resume --rounds`, carry it on.
func AtBudget(record *Object) bool {
	rounds := FirstNumber(record, "rounds")
	return record.Str("state") == "fail" && !record.Truthy("review_pr") && isDir(worktree(record)) &&
		rounds > 0 && float64(len(record.List("round_summaries"))) >= rounds
}

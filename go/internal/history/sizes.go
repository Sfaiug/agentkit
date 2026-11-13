package history

import (
	"strings"

	"agentkit/internal/run"
)

// FirstReviewSizes is, for the Limits page's line limits (menu.SizeChart), the runs realWork counts
// that ended with a verdict on the work (run.Judged), Python's history.first_review_sizes: builds,
// then own pull requests, each row its started_at, its lines and whether it passed, in start order.
// A build is no own pull request and reviews none, its lines its first review's, passed in round 1;
// an own pull request (kind `seat PR` or own_orchestrator set) is a change's runs, its lines its
// largest first review's, passed where one merged in round 1 -- a pass need not merge, as with
// --no-merge.  None where the database cannot answer.  It reads runs as the migration would leave
// them, so a history from before runs had a kind answers too and opening the page writes nothing.
func FirstReviewSizes() (builds, own []Row) {
	db := Look()
	defer db.Close()
	if db == nil {
		return nil, nil
	}
	runs := db.migrated("runs")
	mine := "(kind IS 'seat PR' OR COALESCE(own_orchestrator, '') <> '')"
	judged := make([]any, len(run.Judged))
	for i, state := range run.Judged {
		judged[i] = state
	}
	// realWork last: it reads a run's record, which the columns spare most rows
	counted := "final_state IN (" + strings.Repeat("?, ", len(judged)-1) + "?) AND " + realWork
	builds, built := db.read("SELECT started_at, first_review_lines AS lines, "+
		"rounds_used IS 1 AND final_state IS 'pass' AS passed FROM "+runs+" WHERE "+
		"first_review_lines IS NOT NULL AND NOT "+mine+" AND COALESCE(\"change\", '') NOT LIKE '%#%' "+
		"AND run_id NOT LIKE '%-review-pr-%' AND "+counted+" ORDER BY started_at", judged...)
	own, owned := db.read("SELECT MIN(started_at) AS started_at, MAX(first_review_lines) AS lines, "+
		"MAX(changed_lines IS NOT NULL AND rounds_used IS 1) AS passed FROM "+runs+" WHERE "+mine+
		" AND "+counted+" GROUP BY COALESCE(\"change\", run_id) HAVING MAX(first_review_lines) "+
		"IS NOT NULL ORDER BY 1", judged...)
	// either failing answers neither, as Python's one try does
	if !built || !owned {
		return nil, nil
	}
	return builds, own
}

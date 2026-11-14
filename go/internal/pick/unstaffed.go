package pick

import (
	"fmt"
	"slices"
	"strings"
)

// Unstaffed is the sentence a run is refused with when no executor or no reviewer of its groups
// can run here, Python's staffing.pair_refusal: budgets refill and are no part of it, while nothing
// refills a harness that cannot run.  cannot says why of each model that cannot.  "" where one of
// each can, or where every reviewer is barred from reviewing, which Python words otherwise.
func (r *Rules) Unstaffed(cannot map[string]string) string {
	able := func(name string) bool { return cannot[name] == "" }
	lacksExecutor, lacksReviewer := !slices.ContainsFunc(r.executors, able), !r.alone && !slices.ContainsFunc(r.reviewers, able)
	if !r.alone && len(r.reviewers) == 0 || !lacksExecutor && !lacksReviewer {
		return ""
	}
	var missing, why []string
	if lacksExecutor {
		missing = append(missing, "workers "+strings.Join(r.executors, ", "))
	}
	if lacksReviewer {
		missing = append(missing, "reviewers "+strings.Join(r.reviewList, ", "))
	}
	var said []string
	for _, name := range slices.Concat(r.executors, r.reviewList) {
		if reason := cannot[name]; reason != "" && !slices.Contains(said, name) {
			said = append(said, name)
			why = append(why, name+": "+reason)
		}
	}
	return fmt.Sprintf("none of the %s can run here (%s); log in to another harness or add another model to the groups",
		strings.Join(missing, " and "), strings.Join(why, "; "))
}

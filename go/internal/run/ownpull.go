package run

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
)

// replacedWithin is how long a pull request that failed at its budget still charges the one that
// re-adds its lines, Python's REPLACED_WITHIN.
const replacedWithin = 14 * 24 * time.Hour

// PullLeft is the rounds the review of a seat's own pull request the record names may still have,
// its budget less what its other runs and this one (own) spent on it, and why none, Python's
// own_pr_budget: the budget is the pull request's, so a relaunch inherits what was spent.
func PullLeft(record *Object, dir string, own int, now time.Time) (int, string, error) {
	budget, err := PolicyRounds(record)
	if err != nil {
		return 0, "", err
	}
	number := ""
	if found := pullRequest.FindStringSubmatch(record.Str("review_pr")); found != nil {
		number = found[3]
	}
	return left(record, dir, budget, own, "PR #"+number, now)
}

// PullReviewed is whether a review of that pull request handed in its verdict on any run of it,
// Python's change_reviewed for a pull request.
func PullReviewed(url string) bool {
	for _, dir := range Dirs() {
		if state, _ := Read(dir); state != nil && len(state.List("round_summaries")) > 0 && prKeys(state)[prKey(url)] {
			return true
		}
	}
	return false
}

// BudgetFailed is each pull request of that repository whose review spent the budget across its
// runs, none of which merged, as (its URL, the commit its size counts against, its head) of each run
// of it that ended `fail` within replacedWithin, once, the run at exclude aside, Python's
// budget_failed_reviews: what a replacement inherits its rounds from.
func BudgetFailed(repo string, budget int, exclude string, now time.Time) [][3]string {
	type failed struct{ pr, base, head string }
	var order []failed
	urls := map[failed]string{}
	merged, spent := map[string]bool{}, map[string]int{}
	for _, dir := range Dirs() {
		state, _ := Read(dir)
		if state == nil || filepath.Base(dir) == filepath.Base(exclude) {
			continue
		}
		keys := prKeys(state)
		for key := range keys {
			spent[key] += roundsSpent(state, now)
			merged[key] = merged[key] || state.Truthy("merged")
		}
		finished, _ := Num(state.Get("finished_at"))
		base := Text(state.Get(firstKey(state, "target_sha", "base_sha")))
		if state.Truthy("merged") || !state.Truthy("review_pr") || state.Str("state") != "fail" || !sameRepo(state.Str("repo"), repo) ||
			base == "" || !state.Truthy("head_sha") || now.Sub(time.Unix(0, int64(finished*1e9))) > replacedWithin {
			continue
		}
		each := failed{prKey(state.Get("review_pr")), base, state.Str("head_sha")}
		if _, seen := urls[each]; !seen {
			order = append(order, each)
			urls[each] = state.Str("review_pr")
		}
	}
	var found [][3]string
	for _, each := range order {
		if !merged[each.pr] && spent[each.pr] >= budget {
			found = append(found, [3]string{urls[each], each.base, each.head})
		}
	}
	return found
}

// prKeys is the pull requests a run is on: a task run keeps its own in `pr`, a review in `review_pr`.
func prKeys(record *Object) map[string]bool {
	keys := map[string]bool{}
	for _, key := range []string{"pr", "review_pr"} {
		if found := prKey(record.Get(key)); found != "" {
			keys[found] = true
		}
	}
	return keys
}

// sameRepo is whether two recorded checkouts name one repository.
func sameRepo(a, b string) bool {
	return a != "" && b != "" && config.Resolve(a) == config.Resolve(b)
}

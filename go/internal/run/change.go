package run

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
)

// branchGone is whether the run's local branch went with its checkout, Python's record.branch_gone.
func branchGone(record *Object) bool {
	return record.Str("state") == "stopped" && !record.Truthy("stop_kept") || record.Str("state") == "not_needed" ||
		record.Truthy("merged") || record.Truthy("branch_removed")
}

// ChangeOn is the change a launch `from:` that branch continues, nil where the name is free,
// Python's change_on: the change of the newest other run of that repository ak cut the branch for
// and whose branch still stands.  A branch name is no change: what took the branch gives the name
// back to the next task of that title, and a run in the repository itself owns none.
func ChangeOn(branch, repo, dir string) any {
	var owner *Object
	newest := ""
	for _, other := range Dirs() {
		id := filepath.Base(other)
		if id == filepath.Base(dir) {
			continue
		}
		state, _ := Read(other)
		if state == nil || state.Str("branch") != branch || !state.Truthy("worktree") || !state.Truthy("repo") ||
			filepath.Clean(state.Str("worktree")) == filepath.Clean(state.Str("repo")) ||
			config.Resolve(state.Str("repo")) != config.Resolve(repo) || branchGone(state) || id <= newest {
			continue
		}
		owner, newest = state, id
	}
	if owner == nil {
		return nil
	}
	owner = owner.Copy()
	owner.Set("run_id", newest)
	return changeOf(owner)
}

// ChangeName is the name a run's change is recorded under, Python's change_name: the pull request
// it reviews, however its URL was spelled, else its change.
func ChangeName(record *Object) any {
	if key := prKey(record.Get("review_pr")); key != "" {
		return key
	}
	return changeOf(record)
}

// BranchLeft is ChangeLeft for a launch that continues that change on that branch: the rounds the
// run may have, and why none, as Python's round_budget says it of a `from:`.
func BranchLeft(record *Object, dir string, change any, branch string, asked int, now time.Time) (int, string, error) {
	onto := record.Copy()
	onto.Set("change", change)
	return left(onto, dir, asked, 0, "branch "+branch, now)
}

// ChangeReviewed is whether a review of the run's change handed in its verdict on any of its runs,
// Python's change_reviewed.
func ChangeReviewed(record *Object) bool {
	change := changeOf(record)
	for _, other := range Dirs() {
		state, _ := Read(other)
		if change != nil && state != nil && len(state.List("round_summaries")) > 0 && Equal(changeOf(state), change) {
			return true
		}
	}
	return false
}

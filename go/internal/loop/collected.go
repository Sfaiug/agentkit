package loop

import (
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// What the collector takes of a run as every other way a checkout goes takes it.

// StopCheckout is stopCheckout for the collector: a run's worktree, and its branch unless kept.
func StopCheckout(dir string, record *run.Object, log func(string), keepBranch bool) bool {
	return stopCheckout(dir, record, log, keepBranch)
}

// DropBranch is dropBranch for the collector: the run's local `ak/` branch, in its repository.
func DropBranch(repo, branch string, log func(string)) bool {
	return dropBranch(gitcall.Git{Repo: repo}, branch, log)
}

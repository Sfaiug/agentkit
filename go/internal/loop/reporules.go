package loop

import "agentkit/internal/changerules"

// filesScope is the failure for paths the branch changes outside the task's `files:` pathspecs,
// "" for none.
func (r *repoPlace) filesScope() (string, error) {
	return changerules.Scope(r.git(), r.baseSHA, "HEAD", r.files)
}

// rulesCheck is the branch's refusal under the change rules, "" for none.
func (r *repoPlace) rulesCheck() (string, error) {
	return changerules.Check(r.git(), r.baseSHA, "HEAD")
}

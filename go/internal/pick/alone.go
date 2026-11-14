package pick

// Alone is these rules for a run with review off, Python's pick_models with want_review False: the
// executor makes the pair by itself, and no reviewer is staffed or ordered.
func (r *Rules) Alone() *Rules {
	alone := *r
	alone.alone = true
	return &alone
}

// first is the pair of the first of these executors alone, false for none.
func first(executors []string) (string, string, bool) {
	if len(executors) == 0 {
		return "", "", false
	}
	return executors[0], "", true
}

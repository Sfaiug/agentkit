package loop

import (
	"slices"

	"agentkit/internal/history"
)

// rows is what the history rows of a check the round runs name: its kind, on tree, "" for a
// scratch run's one workspace.
func (l *loop) rows(kind, tree string) *history.Checked {
	return &history.Checked{Run: l.id, Round: l.rnd, Kind: kind, Tree: tree}
}

// rulesOn is the round's rules on tree, Python's files_scope and rules_check under one row: each
// check's failure, "" for none, the row's exit 1 where any failed.
func (l *loop) rulesOn(tree string, checks ...func() (string, error)) ([]string, error) {
	finish := history.Check(l.rows("rules", tree), "files_scope, rules_check", clock(), "", l.say)
	var exit *int
	defer func() { finish(exit) }()
	failures := make([]string, len(checks))
	for i, check := range checks {
		var err error
		if failures[i], err = check(); err != nil {
			return nil, err
		}
	}
	code := 0
	if slices.ContainsFunc(failures, func(failure string) bool { return failure != "" }) {
		code = 1
	}
	exit = &code
	return failures, nil
}

// exitOf is how a check that ran ended as its row keeps it: its exit, nil where it never returned.
func exitOf(ended ran, err error) *int {
	if err != nil || ended.stopped != "" {
		return nil
	}
	return &ended.code
}

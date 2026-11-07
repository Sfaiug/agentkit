package handin

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/changerules"
	"agentkit/internal/gitcall"
	"agentkit/internal/uncommitted"
)

// checkWorkspace refuses a builder's done while its workspace, as the loop will commit it, changes
// a path outside the task's `files:`, breaks the change rules or adds past its line limit, every
// failure in one refusal, Python's hand_in.check_workspace: counted from the run's base less what
// an integration brought in from the target, with the attributes read from the index the loop will
// leave, borrowed beside the checkout.  A scratch run has no base to count from.
func (t *turn) checkWorkspace(beside string) error {
	if t.checks == nil || !t.checks.Truthy("base") || t.checks.Truthy("scratch") {
		return nil
	}
	workspace, isPath := t.workspace.(string)
	base, isBase := t.checks.Get("base").(string)
	if !isPath || !isBase {
		return ErrPython
	}
	var specs []string
	for _, each := range t.checks.List("files") {
		spec, ok := each.(string)
		if !ok {
			return ErrPython
		}
		specs = append(specs, spec)
	}
	artifacts := map[string]bool{}
	for _, name := range t.checks.List("artifacts") {
		if name, ok := name.(string); ok {
			artifacts[name] = true
		}
	}
	g := gitcall.Git{Repo: workspace}
	upstream, err := t.upstream(g)
	if err != nil {
		return err
	}
	if upstream != "" {
		if base, err = gitcall.IntegratedBase(g, base, upstream); err != nil {
			return err
		}
	}
	tmp, err := os.MkdirTemp(beside, "")
	if err != nil {
		return ErrPython
	}
	defer os.RemoveAll(tmp)
	index := filepath.Join(tmp, "index")
	tree, err := uncommitted.Tree(g, artifacts, index)
	if err != nil {
		return err
	}
	scope, err := changerules.Scope(g, base, tree, specs)
	if err != nil {
		return err
	}
	rules, err := changerules.Check(gitcall.Git{Repo: workspace, Env: []string{"GIT_INDEX_FILE=" + index}}, base, tree)
	if err != nil {
		return err
	}
	lines, err := t.oversize(g, base, tree)
	if err != nil {
		return err
	}
	failures := slices.DeleteFunc([]string{scope, rules, lines}, func(failure string) bool { return failure == "" })
	if len(failures) == 0 {
		return nil
	}
	return errors.New("done refused: " + strings.Join(failures, "\n"))
}

// upstream is the target the turn's base follows, "" for none: a turn of an older loop named only
// its base, where a single remote tip is unambiguous.
func (t *turn) upstream(g gitcall.Git) (string, error) {
	switch named := t.checks.Get("upstream").(type) {
	case string:
		return named, nil
	case nil:
		listed, err := g.Must("for-each-ref", "--format=%(objectname)", "refs/remotes/")
		tips := slices.Compact(slices.Sorted(slices.Values(strings.Fields(listed))))
		if err != nil || len(tips) != 1 {
			return "", err
		}
		return tips[0], nil
	}
	return "", ErrPython
}

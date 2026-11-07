package launch

import (
	"cmp"
	"errors"
	"io"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Night starts a failed night's fix run from its task file at path, as Python's nightly._start
// does: none where the task is refused as written (Refusal) or a run of it is under way (the
// launch's own check), else one launched on no seat, bound to the marked executors, else the
// orchestrator, and to the marked reviewers, its receipt saying origin.  The run's id, or why
// none started; ErrPython for a launch Go leaves to Python.
func Night(path string, origin *run.Object) (string, error) {
	meta, cmds, err := task.Read(path)
	if err != nil {
		return "", err
	}
	if why, err := Refusal(path, meta, cmds); err != nil || why != "" {
		return "", cmp.Or(err, errors.New(why))
	}
	marked, err := config.Defaults()
	bound, unbound := config.Bind()
	if err != nil || unbound != nil {
		return "", ErrPython
	}
	workers, reviewers := marked.Workers, marked.Reviewers
	if len(workers) == 0 {
		workers = []string{marked.Orchestrator}
	}
	if reviewers == nil {
		reviewers = workers
	}
	bound.Workers, bound.Reviewers = nil, nil
	for _, name := range workers {
		bound.Workers = append(bound.Workers, name)
	}
	for _, name := range reviewers {
		bound.Reviewers = append(bound.Reviewers, name)
	}
	dir, _, why, err := launcher{bound: bound, origin: origin}.launch(path, nil, map[string]bool{"--bg": true}, io.Discard, io.Discard)
	if err == nil && why != "" {
		err = errors.New(why)
	}
	if err != nil {
		return "", err
	}
	return filepath.Base(dir), nil
}

// unstaffed is why no pair of the bound lists can run here, "" where one can.
func unstaffed(bound config.Binding) string {
	rules, ok := pick.Within(names(bound.Workers), names(bound.Reviewers))
	if !ok {
		return ""
	}
	return loop.Unstaffed(rules)
}

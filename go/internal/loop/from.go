package loop

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// onChange is the change a launch `from:` a branch continues, nil for none, with the rounds the
// earlier runs on it left this one taken off its budget: it is the change's, not the run's.
func (r *repoPlace) onChange(l *loop, path string) (any, error) {
	if r.from == "" {
		return nil, nil
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return nil, err
	}
	change := run.ChangeOn(r.from, r.repo, l.dir)
	left, why, err := run.BranchLeft(record, l.dir, change, r.from, l.budget, time.Now())
	if err != nil {
		return nil, err
	}
	if left < 1 {
		return nil, errors.New(path + ": " + why)
	}
	l.budget = left
	return change, nil
}

// takeInTarget merges what the work lands on into a checkout cut from a branch, Python's loop before
// round 1, its commit pinned so another worktree's fetch cannot move it.  A conflict is no failure:
// the branch stays as it was and takes that in at landing.
func (r *repoPlace) takeInTarget(l *loop) error {
	g := r.git()
	upstream := r.upstream()
	source := upstream
	tip, err := g.Try("rev-parse", "--verify", "--quiet", "refs/remotes/"+upstream+"^{commit}")
	if err != nil {
		return err
	}
	if tip == "" {
		name := strings.TrimPrefix(upstream, "origin/")
		source = "local " + name
		if tip, err = g.Try("rev-parse", "--verify", "--quiet", "refs/heads/"+name+"^{commit}"); err != nil {
			return err
		}
	}
	if tip == "" {
		l.say(fmt.Sprintf("from: %s unavailable; branch unchanged; %s will be taken in at landing", upstream, upstream))
		return nil
	}
	l.say(fmt.Sprintf("from: merging %s (%s) into %s before round 1", source, tip[:12], r.branch))
	code, out, err := g.Out("merge", "--no-edit", tip)
	if err != nil {
		var stopped *gitcall.Stopped
		if errors.As(err, &stopped) {
			g.Try("merge", "--abort")
		}
		return err
	}
	if code != 0 {
		conflicted, err := g.Try("diff", "--name-only", "--diff-filter=U")
		if err != nil {
			return err
		}
		if conflicted == "" {
			return fmt.Errorf("could not merge %s before round 1: %s", source, out)
		}
		if _, err := g.Must("merge", "--abort"); err != nil {
			return err
		}
		l.say(fmt.Sprintf("from: %s conflicts; merge aborted, branch unchanged; %s will be taken in at landing", source, upstream))
		return nil
	}
	r.baseSHA = tip
	if err := l.save(func(record *run.Object) { record.Set("base_sha", tip) }); err != nil {
		return err
	}
	l.say(fmt.Sprintf("from: merged %s into %s before round 1", source, r.branch))
	return nil
}

package loop

import (
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/run"
)

// meetTarget is Python's rebase_for_review with the follow_target after it: before a round checks
// and reviews the work, the target's moves that touch the branch's files are taken in, and those
// that do not are kept out, so the review keeps its base.  A target that cannot be fetched is met
// as last fetched; a landing's recheck of a completed round leaves it to its own integration.
func (r *repoPlace) meetTarget(l *loop) error {
	upstream, g := r.upstream(), r.git()
	record, err := read(l)
	if err != nil {
		return err
	}
	fresh := upstream != "" && l.rnd > len(record.List("round_summaries"))
	if fresh {
		code, _, err := g.Fetch("origin", strings.TrimPrefix(upstream, "origin/"))
		if err != nil {
			return err
		}
		if code != 0 {
			l.say("WARN cannot fetch " + upstream + ": the review meets it as last fetched")
			fresh = false
		}
	}
	if err := r.followTarget(l); err != nil || !fresh {
		return err
	}
	tip, err := g.Must("rev-parse", upstream+"^{commit}")
	if err != nil {
		return err
	}
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	code, _, err := g.Out("merge-base", "--is-ancestor", tip, "HEAD")
	if err != nil || code == 0 {
		return err
	}
	if apart, err := r.disjoint(head, tip); err != nil || apart {
		return err
	}
	// the review's base moves: it reads the whole change, never mapping the head it read before
	if err := l.save(func(record *run.Object) { record.Delete("delta_from") }); err != nil {
		return err
	}
	how, err := r.how(record)
	if err != nil {
		return err
	}
	verb := "rebasing"
	if how == "merge" {
		verb = "merging"
	}
	l.say(fmt.Sprintf("--- round %d: %s onto %s (%s)", l.rnd, verb, upstream, tip[:12]))
	carried, fixed, err := r.integrateTip(l, upstream, how, tip, false)
	if err != nil {
		return err
	}
	if !carried {
		record, err := read(l)
		if err != nil {
			return err
		}
		return &exhausted{record.Str("merge_note"), false}
	}
	if fixed {
		if err := l.step("done-when"); err != nil {
			return err
		}
	}
	return l.save(func(record *run.Object) {
		record.Set("rebases", append(record.List("rebases"), run.Fields("round", l.rnd, "onto", tip, "method", how)))
	})
}

// disjoint is whether the target's moves since the base touch none of the files the branch changed,
// Python's target_disjoint_from_branch: a clean rebase then changes only the parent.  What git
// cannot compare overlaps.
func (r *repoPlace) disjoint(head, tip string) (bool, error) {
	var sides [2][]string
	for i, end := range []string{head, tip} {
		// unstripped: a first name can start with a space
		code, out, _, err := r.git().Run("diff", "--no-renames", "--name-only", "-z", r.baseSHA, end)
		if err != nil || code != 0 {
			return false, err
		}
		sides[i] = paths(out)
	}
	return !slices.ContainsFunc(sides[0], func(path string) bool { return slices.Contains(sides[1], path) }), nil
}

// integrateTip takes tip into the branch the way how says, the one integration a round and the
// merge both make, and makes it the run's base: whether the branch carries it, and whether that took
// a conflict's fixer (resolve, rechecking as recheck says).  A git that stopped puts the branch back.
func (r *repoPlace) integrateTip(l *loop, upstream, how, tip string, recheck bool) (carried, fixed bool, err error) {
	code, out, err := r.git().Out(integration(how, tip)...)
	if err != nil {
		r.abort(l, how, true)
		return false, false, err
	}
	if code != 0 {
		carried, err := r.resolve(l, upstream, how, tip, out, recheck)
		return carried, true, err
	}
	return true, false, r.setBase(l, tip)
}

// setBase makes sha the run's base and target, Python's set_base: what the diff, the suite and a
// review's `users:` read from, whatever a later fetch moves the target's ref to.  A PR review judges
// what that integration left (pin).
func (r *repoPlace) setBase(l *loop, sha string) error {
	r.baseSHA, l.usersAt = sha, sha
	if err := l.save(func(record *run.Object) { run.SetAll(record, "base_sha", sha, "target_sha", sha) }); err != nil {
		return err
	}
	return r.pin(l)
}

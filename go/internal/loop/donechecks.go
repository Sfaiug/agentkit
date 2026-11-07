package loop

import (
	"maps"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// doneChecks is what a builder's `ak hand-in done` holds a turn of that word to, the part of Python's
// turn checks Go's hand-in reads: the task's own checks each round, a suite split into shards left
// out as the repository's, the base its count starts from and the target it follows, the task's
// `files:`, that the run is no scratch one, the artifacts the loop's commit leaves out, as `lines`
// the first review's ceiling for an executor whose change waits for that review, the count the
// gate after the turn makes, else no limit, and the run's ceiling and silence the checks run under.
func (r *repoPlace) doneChecks(l *loop, word string) *run.Object {
	lines := config.NoLimit
	if word == "executor" && r.firstReviewDue(l) {
		lines = l.reviewLines
	}
	files := []any{}
	for _, spec := range r.files {
		files = append(files, spec)
	}
	artifacts := []any{}
	for _, name := range slices.Sorted(maps.Keys(r.artifacts)) {
		artifacts = append(artifacts, name)
	}
	return run.Fields("commands", ownChecks(l), "base", r.baseSHA, "upstream", r.upstream(), "files", files, "scratch", false, "artifacts", artifacts, "lines", lines.Said(),
		"limit", seconds(l.ceiling), "silence", seconds(l.silence))
}

// seconds is a bound as Python's record writes it, 3600 * ceiling_hours or 60 * silence_minutes:
// a whole number of seconds as an int.
func seconds(bound time.Duration) any {
	if bound%time.Second == 0 {
		return int(bound / time.Second)
	}
	return bound.Seconds()
}

// ownChecks is what judges a change each round, Python's own_checks: the task's per-round checks
// less a suite split into shards, which is the repository's, not the change's.
func ownChecks(l *loop) []any {
	commands := []any{}
	for _, cmd := range l.every {
		if !namesShard.MatchString(cmd) {
			commands = append(commands, cmd)
		}
	}
	return commands
}

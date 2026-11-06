package loop

import (
	"maps"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// doneChecks is what a builder's `ak hand-in done` holds a turn of that word to, the part of Python's
// turn checks Go's hand-in reads: the task's own checks each round, a suite split into shards left
// out as the repository's, the base its count starts from and the target it follows, the artifacts
// the loop's commit leaves out, and as `lines` the first review's ceiling for an executor whose
// change waits for that review, the count the gate after the turn makes, else no limit.
func (r *repoPlace) doneChecks(l *loop, word string) *run.Object {
	lines := config.NoLimit
	if word == "executor" && r.firstReviewDue(l) {
		lines = l.reviewLines
	}
	commands := []any{}
	for _, cmd := range l.every {
		if !namesShard.MatchString(cmd) {
			commands = append(commands, cmd)
		}
	}
	artifacts := []any{}
	for _, name := range slices.Sorted(maps.Keys(r.artifacts)) {
		artifacts = append(artifacts, name)
	}
	return run.Fields("commands", commands, "base", r.baseSHA, "upstream", r.upstream(), "artifacts", artifacts, "lines", lines.Said())
}

// A scratch run has no base to count its change from.
func (scratch) doneChecks(*loop, string) *run.Object { return nil }

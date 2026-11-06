package loop

// A test piece the kernel killed for memory, Python's gate._SuiteMeasure.starved and the rerun in
// gate._run_suite: one that died by SIGKILL while its cgroup's `oom_kill` count rose meanwhile ran
// out of memory, which says nothing of its tests.  It runs once more after its siblings; out of
// memory again there, or where a red piece's failed tests run again alone, it is red only where
// no other piece is, and then the host's red, nobody's, Python's land.red_part `short`: the
// landing pass ends with no verdict.

import (
	"fmt"

	"agentkit/internal/host"
)

// starved is whether a piece that ended so, the cgroup's count at kills as it started, ran out of
// memory: a test may exit 137 on its own, and one stopped at its limit died by its watch.
func starved(ended ran, kills int) bool {
	return ended.stopped == "" && (ended.code == 137 || ended.code == -9) && host.OOMKills() > kills
}

// short is whether the checks' red is the host's: no member is sent to its fixer and the target's
// tip is not probed, as the next pass checks the tree again, Python's land._check_tree.
func (s *narrowingStack) short(selection *checkSelection) bool {
	if selection.red == nil || !selection.red.Truthy("short") {
		return false
	}
	s.l.say(fmt.Sprintf("AK_SHARD=%s of %s's tree ran out of memory again, run alone: nobody is blamed; the next pass checks it again", selection.red.Str("piece"), s.l.id))
	return true
}

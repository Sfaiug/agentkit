package loop

import (
	"strings"

	"agentkit/internal/run"
)

// redPatch is what a landing red keeps for the run's row to count once it merges, Python's
// landing_red_patches entry: whether it is the work's own tests going red, and if so the patch id
// of the work as the lander checked it, nil where git cannot say.  A merge that keeps that patch
// shows the red was a flake; anything else is a break (history's landingCounts).
func (r *repoPlace) redPatch(record, fix *run.Object) (any, bool, error) {
	if !suiteRed(record, fix) {
		return nil, false, nil
	}
	id, err := r.git().PatchID(r.baseSHA, "HEAD")
	if err != nil {
		return nil, false, err
	}
	if id == "" {
		return nil, true, nil
	}
	return id, true, nil
}

// suiteRed is Python's suite_red: a piece red on its tree after the target alone passed, or a
// required check failed.  A conflict with the target, a head moved past its review, a red target
// or the rules' size says nothing of what review let through, nor does a piece a target's repair
// fails, as it lands on the red target, which the lander never probes for it.
func suiteRed(record, fix *run.Object) bool {
	return fix.Has("piece") && !record.Truthy("repair") || strings.HasPrefix(fix.Str("line"), "required checks failed:")
}

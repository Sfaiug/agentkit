package loop

import (
	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// StartRepair is a repair the tick starts on the seat state names, as watch.after_merge_revert does
// through start_followups: handback.StartRepair, prepared by launchForSeat. ErrLeft, nothing
// written, where Go does not carry its launch (carried).
func StartRepair(state *run.Object, dir string, repair *run.Object, say func(string)) (string, error) {
	if err := carried(state, run.Fields("repo", state.Str("repo"))); err != nil {
		return "", err
	}
	return handback.StartRepair(state, dir, repair, launchForSeat, say)
}

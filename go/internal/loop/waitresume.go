package loop

import "agentkit/internal/run"

// waitingPickup admits a merge wait whose saved review still covers its checkout. Other
// recovery points keep Python's review reconstruction and provider handover.
func waitingPickup(dir string, record *run.Object) bool {
	if record.Str("state") != "waiting" || landingLine(record) != "" || !unitless(record) || run.ProcessActive(record) ||
		!record.Truthy("repo") || !record.Truthy("executor") || !record.Truthy("reviewer") || !record.Has("round_summaries") {
		return false
	}
	for _, key := range pythonRoads {
		if key != "waiting_on" && record.Truthy(key) {
			return false
		}
	}
	return run.IntegrationNote(dir, record) && savedIntegrationPass(record) && pairReady(dir, record)
}

func savedIntegrationPass(record *run.Object) bool {
	passed := record.Copy()
	passed.Set("verdict", "PASS")
	if !run.ReviewPass(passed, run.Models()) {
		return false
	}
	head, tree, err := repoFrom(record).identity()
	review := record.Dict("review")
	return err == nil && review.Str("head_sha") == head && review.Str("tree_sha") == tree
}

func resumeWaiting(dir string, record *run.Object) error {
	if !run.IntegrationNote(dir, record) || !savedIntegrationPass(record) {
		return ErrChanged
	}
	record.Set("verdict", "PASS")
	record.Delete("waiting_on")
	return nil
}

package handback

import (
	"strings"

	"agentkit/internal/run"
)

// FollowupReport keeps the plan lines and fix runs named by an ending in its result.
func FollowupReport(state *run.Object) string {
	var deferred, owed, refused, parts []string
	for _, value := range state.List("followup_plan") {
		entry, ok := value.(*run.Object)
		if !ok {
			continue
		}
		switch {
		case entry.Has("refused"):
			refused = append(refused, entry.Str("outcome")+" ("+entry.Str("refused")+")")
		case entry.Truthy("deferred"):
			deferred = append(deferred, entry.Str("outcome"))
		default:
			owed = append(owed, entry.Str("outcome"))
		}
	}
	checked := "checked by the reviewer's probe until its fix is on the default branch or `ak plan check N` puts your own test in its place"
	var sentences []string
	if len(deferred) > 0 {
		sentences = append(sentences, "Review follow-ups now deferred in your plan: "+strings.Join(deferred, "; ")+", each fixed by a run of its own and "+checked+" and makes the line yours.")
	}
	if len(owed) > 0 {
		sentences = append(sentences, "Review follow-ups now in your plan, yours to build: "+strings.Join(owed, "; ")+", each "+checked+".")
	}
	if len(refused) > 0 {
		sentences = append(sentences, "Review follow-ups your plan refused, yours to judge: "+strings.Join(refused, "; ")+".")
	}
	if len(sentences) > 0 {
		parts = append(parts, "## Follow-up plan", "", strings.Join(sentences, " "), "")
	}
	if ids := state.List("followup_runs"); len(ids) > 0 {
		parts = append(parts, "## Fix runs", "")
		for _, id := range ids {
			parts = append(parts, "- "+run.Text(id))
		}
		parts = append(parts, "")
	}
	return strings.Join(parts, "\n")
}

package harness

import (
	"path/filepath"

	"agentkit/internal/run"
)

// museTokenSources is each log of the session the seat's launch reported, and its child
// sessions' logs beside it (muse.py `seat_token_sources`).
func museTokenSources(record *run.Object) []string {
	var sources []string
	for _, log := range museSessionLogs(museConversation(map[string]any{"muse_launch": record.Get("muse_launch")})) {
		sources = append(append(sources, log), below(filepath.Join(filepath.Dir(log), "subagent"), "session.jsonl")...)
	}
	return sources
}

// museTokenUsage is a provider usage the session attributes, dated when Muse recorded it, in
// microseconds (muse.py `seat_token_usage`): Muse says no model or counts by type.
func museTokenUsage(entry, _ *run.Object) (Spend, bool) {
	event := museRunEvent(entry, "goal_usage_attribution")
	recorded, dated := entry.Num("recorded_at")
	if event == nil || event.Dict("record") == nil || !dated {
		return Spend{}, false
	}
	tokens, counted := museProvided(event.Dict("record"))
	return Spend{At: Moment(run.Float(recorded / 1e6)), Event: entry.Str("id"), Tokens: tokens}, counted
}

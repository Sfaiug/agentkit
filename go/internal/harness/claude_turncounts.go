package harness

import (
	"path/filepath"

	"agentkit/internal/run"
)

// claudeTurnCounts is the counts of the turn's last result, claude.py `turn_usage`: its `modelUsage`
// counts its subagents too and totals every turn of its session; a result without one counts this
// turn's own `usage`, under no model.  A turn whose last start is past its last result was killed
// before Claude Code wrote one (claudeKilledCounts).
func claudeTurnCounts(out string) (any, []Counts, bool) {
	result, _ := lastEntry(filepath.Join(out, "events.jsonl"), func(entry *run.Object) bool {
		return entry.Get("type") == "result" || entry.Get("type") == "system" && entry.Get("subtype") == "init"
	})
	if result == nil {
		return nil, nil, false
	}
	if result.Get("type") != "result" {
		return claudeKilledCounts(out, result)
	}
	if models := result.Dict("modelUsage"); models != nil && len(models.Keys()) > 0 {
		var counts []Counts
		for _, model := range models.Keys() {
			counts = append(counts, Counts{model, kinds(models.Dict(model), "inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")})
		}
		return result.Get("session_id"), counts, true
	}
	return nil, []Counts{{nil, kinds(result.Dict("usage"), "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}}, true
}

// kinds is each key's count in usage, 0 where it holds no whole number of at least 0.
func kinds(usage *run.Object, keys ...string) (spent [4]int64) {
	for at, key := range keys {
		if usage == nil {
			break
		}
		if count, ok := usage.Int(key); ok && count >= 0 {
			spent[at] = int64(count)
		}
	}
	return spent
}

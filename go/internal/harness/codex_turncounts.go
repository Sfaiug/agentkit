package harness

import (
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/run"
)

// codexTurn is a kept Codex turn's events file and its thread's total by its end.
type codexTurn struct {
	events string
	total  float64
}

// codexThreadTurn is the total of the turn of that events file among the run's kept Codex turns
// that name their thread and whose total reads, in reporting order, codex.py `_thread_turns`, and
// the same thread's latest earlier such turn, empty for the thread's first: Codex totals the
// thread, so a turn's own share is what grew since.  False where the turn is not one of them.
func codexThreadTurn(events string) (float64, codexTurn, bool) {
	latest := map[string]codexTurn{}
	for _, path := range eventPaths(filepath.Dir(filepath.Dir(filepath.Dir(events)))) {
		lines, _ := jsonLines(path, nil)
		thread := ""
		for _, line := range lines {
			if event, ok := line.(*run.Object); ok && event.Get("type") == "thread.started" {
				thread, _ = event.Get("thread_id").(string)
				break
			}
		}
		total, said := eventTokens(path)
		if thread == "" || !said {
			continue
		}
		if path == events {
			return total, latest[thread], true
		}
		latest[thread] = codexTurn{path, total}
	}
	return 0, codexTurn{}, false
}

// codexTurnCounts is the turn's own counts by type, under the model the worker launched it with,
// codex.py `turn_usage`: each what its last `turn.completed` grew by since the same thread's
// latest earlier turn codexThreadTurn reads, whatever model ran that one, as the turn's sum is;
// none where it has no `turn.completed`.  Codex's events name no model, so the model is the
// worker's receipt, none where that is missing, empty or `default`: Codex then ran one of its
// choosing.
func codexTurnCounts(out string) (any, bool, []Counts, bool) {
	events := filepath.Join(out, "events.jsonl")
	counts, completed := codexCompletedCounts(events)
	if !completed {
		return nil, false, nil, false
	}
	if _, earlier, found := codexThreadTurn(events); found && earlier.events != "" {
		was, _ := codexCompletedCounts(earlier.events)
		for kind := range counts {
			counts[kind] = max(0, counts[kind]-was[kind])
		}
	}
	var model any
	if text, err := os.ReadFile(filepath.Join(out, "model")); err == nil && !slices.Contains([]string{"", "default"}, string(text)) {
		model = string(text)
	}
	return nil, false, []Counts{{model, counts}}, true
}

// codexCompletedCounts is what the last `turn.completed` in that events file totals for its
// thread, by type, codex.py `_completed_counts`: false where it has none.
func codexCompletedCounts(events string) ([4]int64, bool) {
	done, _ := lastEntry(events, func(entry *run.Object) bool { return entry.Get("type") == "turn.completed" })
	if done == nil {
		return [4]int64{}, false
	}
	return codexByType(kinds(done.Dict("usage"), codexRunning...)), true
}

// codexByType is codexRunning's counts as input, cache write, cache read and output, codex.py
// `_by_type`: the input less what was cached or written to the cache.
func codexByType(running [4]int64) [4]int64 {
	fresh, cached, written, output := running[0], running[1], running[2], running[3]
	return [4]int64{max(0, fresh-cached-written), written, cached, output}
}

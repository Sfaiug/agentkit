package harness

import (
	"cmp"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config/adapters"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// TurnMeters is the meters the turn in out reported about its own login, as endpoint meters,
// Python's plugin `turn_meters`: none where its harness prints no limits in its stream.
func TurnMeters(name, out string) []any {
	if hook := plugins[name].turnMeters; hook != nil {
		return hook(out)
	}
	return nil
}

// Tokens is what the turn in out spent, Python's plugin `tokens`: by default what the event log its
// adapter wrote there says, false where nothing says.
func Tokens(name, out string) (float64, bool) {
	if hook := plugins[name].tokens; hook != nil {
		return hook(out)
	}
	return eventTokens(filepath.Join(out, "events.jsonl"))
}

// jsonLines is each line of a text file as Python reads one with errors="replace", decoded, nil
// where it holds no JSON; none where the file cannot be read.  Its callers only read what a line
// counts, so a lone surrogate, which Python reads and a Go string cannot hold, is U+FFFD rather
// than the loss of the whole line.
func jsonLines(path string, keep func(line string) bool) ([]any, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	var found []any
	for _, line := range strings.Split(task.Text(data), "\n") {
		if keep != nil && !keep(line) {
			found = append(found, nil)
			continue
		}
		decoded, _ := run.DecodeShown([]byte(strings.ToValidUTF8(line, "�")))
		found = append(found, decoded)
	}
	return found, true
}

// eventTokens is what the event log at path says a turn spent, Python's history.event_tokens: the
// harness's final usage over the messages it already includes, else each message once, at its
// last usage, known by its id where that is a string and else by its line: a stream may carry a
// message as an event for each content block, each repeating its id and usage.
func eventTokens(path string) (float64, bool) {
	events, read := jsonLines(path, nil)
	if !read {
		return 0, false
	}
	final, finished := 0.0, false
	messages := map[any]float64{}
	for line, event := range events {
		usages(event, false, nil, func(value float64, cumulative bool, id any) {
			if cumulative {
				final, finished = value, true
			} else if named, ok := id.(string); ok {
				messages[named] = value
			} else {
				messages[line] = value
			}
		})
	}
	if finished {
		return math.Trunc(final), true
	}
	total := 0.0
	for _, value := range messages {
		total += value
	}
	return math.Trunc(total), len(messages) > 0
}

// usages calls each with every usage the event node carries, whether it is cumulative and the id
// nearest above it, Python's event_tokens `usages`: a running total or a turn's last is
// cumulative, as is any usage under a closing event.  Only usage envelopes carry counters, as tool
// arguments and generated content may hold any number; a `step_update` is one model call's own
// usage.
func usages(node any, cumulative bool, id any, each func(value float64, cumulative bool, id any)) {
	event, ok := node.(*run.Object)
	if !ok {
		return
	}
	kind := event.Get("kind")
	if event.Has("type") {
		kind = event.Get("type")
	}
	cumulative = cumulative || slices.Contains([]any{"result", "turn.completed", "run_terminal"}, kind)
	if event.Has("id") {
		id = event.Get("id")
	}
	for _, key := range []string{"total_token_usage", "last_token_usage"} {
		if total, ok := counted(event.Get(key)); ok {
			each(total, true, id)
			return
		}
	}
	if value, ok := counted(event.Get("usage")); ok {
		each(value, cumulative, id)
		return
	}
	for _, key := range []string{"message", "payload", "info", "stream", "record", "modelUsage", "step_update"} {
		usages(event.Get(key), cumulative, id, each)
	}
}

// counted is the tokens one usage object counts, Python's event_tokens `count`: its total where it
// says one, else its input and output in either spelling, else the sum of the four counters
// Claude reports; false where it holds none of them.
func counted(value any) (float64, bool) {
	usage, ok := value.(*run.Object)
	if !ok {
		return 0, false
	}
	numbers, lower := map[string]float64{}, map[string]float64{}
	for _, key := range usage.Keys() {
		if number, ok := run.Num(usage.Get(key)); ok && !math.IsInf(number, 0) && !math.IsNaN(number) && number >= 0 {
			numbers[key], lower[strings.ToLower(key)] = number, number
		}
	}
	for _, key := range []string{"total_tokens", "tokens"} {
		if number, ok := numbers[key]; ok {
			return number, true
		}
	}
	_, input := lower["inputtokens"]
	if _, output := lower["outputtokens"]; input || output {
		return lower["inputtokens"] + lower["outputtokens"], true
	}
	total, any := 0.0, false
	for _, key := range []string{"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"} {
		number, ok := numbers[key]
		total, any = total+number, any || ok
	}
	return total, any
}

// eventPaths is the run's kept worker event files in reporting order, Python's
// history.event_paths: by round, then by when each was last written, which orders retries and
// handovers within a round.
func eventPaths(runDir string) []string {
	type kept struct {
		round int
		at    int64
		path  string
	}
	var found []kept
	rounds, _ := os.ReadDir(runDir)
	for _, round := range rounds {
		number, err := strconv.Atoi(strings.TrimPrefix(round.Name(), "round-"))
		if !strings.HasPrefix(round.Name(), "round-") || err != nil {
			continue
		}
		turns, _ := os.ReadDir(filepath.Join(runDir, round.Name()))
		for _, turn := range turns {
			path := filepath.Join(runDir, round.Name(), turn.Name(), "events.jsonl")
			if info, err := os.Stat(path); err == nil {
				found = append(found, kept{number, info.ModTime().UnixNano(), path})
			}
		}
	}
	slices.SortFunc(found, func(a, b kept) int {
		return cmp.Or(cmp.Compare(a.round, b.round), cmp.Compare(a.at, b.at), strings.Compare(a.path, b.path))
	})
	var paths []string
	for _, each := range found {
		paths = append(paths, each.path)
	}
	return paths
}

// codexTokens is the increase the turn in out made in its thread's running total, which is what
// Codex reports, codex.py `tokens`: the run's kept turns read in reporting order, each thread's
// total carried from one to the next; a turn whose stream names no thread is its own total.
func codexTokens(out string) (float64, bool) {
	events := filepath.Join(out, "events.jsonl")
	previous := map[string]float64{}
	for _, path := range eventPaths(filepath.Dir(filepath.Dir(out))) {
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
		spent := max(0, total-previous[thread])
		previous[thread] = total
		if path == events {
			return spent, true
		}
	}
	return eventTokens(events)
}

// museTokens is what the turn in out spent, read from Muse's own session store, muse.py `tokens`:
// `muse exec --json` streams no usage, only the session and the runs the turn opened, and the
// session's log records a provider usage for every model request, owned by its run: earlier turns
// of a resumed session are other runs.  Input tokens already include the cached prefix.
func museTokens(out string) (float64, bool) {
	events, read := jsonLines(filepath.Join(out, "events.jsonl"), nil)
	if !read {
		return 0, false
	}
	var session any // the first the stream names
	runs := map[string]bool{}
	for _, line := range events {
		event, ok := line.(*run.Object)
		if !ok {
			continue
		}
		if stream := event.Dict("stream"); stream != nil && stream.Get("kind") == "session" && session == nil && stream.Truthy("id") {
			session = stream.Get("id")
		}
		if payload := event.Dict("payload"); payload != nil {
			if linked := payload.Dict("run_stream"); linked != nil {
				if id, ok := linked.Get("id").(string); ok {
					runs[id] = true
				}
			}
		}
	}
	id, named := session.(string)
	if !named || !museSession.MatchString(id) || len(runs) == 0 {
		return 0, false
	}
	logs, _ := filepath.Glob(filepath.Join(share(), "muse", "sessions", "*", "*", "*", id, "session.jsonl"))
	total, said := 0.0, false
	for _, path := range logs {
		entries, _ := jsonLines(path, func(line string) bool { return strings.Contains(line, "goal_usage_attribution") })
		for _, entry := range entries {
			if spent, ok := museSpent(entry, runs); ok {
				total, said = total+spent, true
			}
		}
	}
	return total, said
}

// museSpent is the provider tokens a session log entry attributes to one of runs.
func museSpent(entry any, runs map[string]bool) (float64, bool) {
	record := dig(entry, "payload", "event", "record")
	if id, ok := dig(record, "owner").Get("run_id").(string); !ok || !runs[id] {
		return 0, false
	}
	spent, counted := museProvided(record)
	return float64(spent), counted
}

// museProvided is the tokens a usage record counts, muse.py `provider_tokens`: the reported input
// and output a provider usage counts.
func museProvided(record *run.Object) (int, bool) {
	quantity := dig(record, "quantity")
	if record.Truthy("quantity") && record.Dict("quantity") == nil || // what Python cannot read as one
		record.Get("usage_family") != "provider" || quantity.Get("reported") == false {
		return 0, false
	}
	total, counted := 0, false
	for _, key := range []string{"input_tokens", "output_tokens"} {
		if count, ok := quantity.Int(key); ok && count >= 0 {
			total, counted = total+count, true
		}
	}
	return total, counted
}

// dig is the object under each key in turn, empty where one is not an object.
func dig(value any, keys ...string) *run.Object {
	found, _ := value.(*run.Object)
	for _, key := range keys {
		if found == nil {
			break
		}
		found = found.Dict(key)
	}
	if found == nil {
		return run.NewObject()
	}
	return found
}

// claudeTurnMeters is the login's limits the turn printed in its own stream, as endpoint meters,
// claude.py `turn_meters`: every `claude -p` turn prints events (adapters.ClaudeLimits) carrying
// its five-hour and seven-day utilizations, 0 to 1, with their resets, so the turn's own login is
// measured with no request.  The last event with a valid window is the reading.
func claudeTurnMeters(out string) []any {
	limits := adapters.ClaudeLimits
	events, _ := jsonLines(filepath.Join(out, "events.jsonl"), func(line string) bool { return strings.Contains(line, limits.Event) })
	var found []any
	for _, line := range events {
		event, ok := line.(*run.Object)
		if !ok || event.Get("type") != limits.Event {
			continue
		}
		info := event.Dict(limits.Info)
		if info == nil || info.Dict("unifiedWindows") == nil {
			continue
		}
		windows := info.Dict("unifiedWindows")
		var meters []any
		// the session window is usage's sessionSecs, the week seven days, as adapters/claude.sh names them
		for _, window := range []struct {
			key, name string
			secs      int
		}{{"five_hour", "session", 18000}, {"seven_day", "weekly_all", 604800}} {
			reading := windows.Dict(window.key)
			if reading == nil {
				continue
			}
			share, measured := run.Num(reading.Get("utilization"))
			resets, dated := run.Num(reading.Get("resetsAt"))
			if !measured || math.IsNaN(share) || share < 0 || share > 1 || !dated || math.IsInf(resets, 0) || math.IsNaN(resets) || resets <= 0 {
				continue
			}
			meters = append(meters, run.Fields("name", window.name, "used", share*100, "resets_at", reading.Get("resetsAt"), "window_secs", window.secs))
		}
		if len(meters) > 0 {
			found = meters
		}
	}
	return found
}

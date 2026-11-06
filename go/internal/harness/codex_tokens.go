package harness

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// codexRunning are the running counts a step's `total_token_usage` holds, its input counting the
// cached and cache-written input too, its output the reasoning (codex.py RUNNING).
var codexRunning = []string{"input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens"}

// codexTokenSources is the rollout the seat's launch reported, while it is one, and the rollouts
// of the threads it spawned (codex.py `seat_token_sources`): a remote seat's private store holds
// every thread of its and their subagents', on every login; any other seat's are found in
// ~/.codex from the thread its record names.
func codexTokenSources(record *run.Object) []string {
	receipt := codexReceipt(record)
	if receipt == nil {
		receipt = run.NewObject()
	}
	var paths []string
	if path, _ := field(receipt, "event", "transcript_path").(string); path != "" {
		if info, err := os.Stat(path); err == nil && info.Mode().IsRegular() {
			paths = append(paths, path)
		}
	}
	codex := filepath.Join(config.UserHome(), ".codex")
	if remote := receipt.Str("remote"); remote != "" {
		return append(paths, below(filepath.Join(codex, "agentkit-seats", remote), "rollout-*.jsonl")...)
	}
	if thread := record.Str("conversation"); thread != "" {
		paths = append(paths, codexFamily(codex, thread)...)
	}
	return paths
}

// codexFamily is the rollouts under Codex's sessions and archived sessions of that thread and of
// each it spawned, at any depth, each told by its first line alone, never another session's
// messages (token_family).
func codexFamily(codex, thread string) []string {
	found, children := map[string]string{}, map[string][]string{}
	for _, folder := range []string{"sessions", "archived_sessions"} {
		for _, path := range below(filepath.Join(codex, folder), "rollout-*.jsonl") {
			file, err := os.Open(path)
			if err != nil {
				continue
			}
			first, _ := bufio.NewReader(file).ReadBytes('\n')
			file.Close()
			value, _ := run.DecodeShown(first)
			meta, _ := field(value, "payload").(*run.Object)
			if meta == nil || !meta.Has("id") {
				continue
			}
			session, _ := meta.Get("id").(string)
			parent, _ := field(meta, "source", "subagent", "thread_spawn", "parent_thread_id").(string)
			found[session] = path
			children[parent] = append(children[parent], session)
		}
	}
	var family []string
	seen := map[string]bool{}
	for pending := []string{thread}; len(pending) > 0; {
		session := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		if seen[session] {
			continue
		}
		seen[session] = true
		pending = append(pending, children[session]...)
		if path, ok := found[session]; ok {
			family = append(family, path)
		}
	}
	return family
}

// codexTokenUsage is each step of the thread's running total, counted once by the total it
// reached, as what it grew by since the last step: Codex counts before its first turn with no
// usage yet, and may count one total twice (codex.py `seat_token_usage`).  The cursor carries the
// total, its counts and the model of the turn under way from one line to the next.
func codexTokenUsage(entry, cursor *run.Object) (Spend, bool) {
	payload := entry.Dict("payload")
	if payload == nil && entry.Truthy("payload") {
		return Spend{}, false
	}
	if payload == nil {
		payload = run.NewObject()
	}
	if entry.Get("type") == "turn_context" {
		model, named := payload.Get("model").(string)
		if named {
			cursor.Set("model", model)
		} else {
			cursor.Set("model", nil)
		}
		return Spend{}, false
	}
	usage, _ := field(payload, "info", "total_token_usage").(*run.Object)
	if usage == nil {
		usage = run.NewObject()
	}
	total, whole := usage.Int("total_tokens")
	at := Moment(entry.Get("timestamp"))
	if entry.Get("type") != "event_msg" || payload.Get("type") != "token_count" || !whole || total < 0 || at == 0 {
		return Spend{}, false
	}
	known := cursor.Has("running") || !cursor.Has("total")
	previous, _ := cursor.Int("total")
	before := cursor.List("running")
	running, grown := make([]any, len(codexRunning)), make([]int, len(codexRunning))
	for i, key := range codexRunning {
		now, _ := usage.Int(key)
		now = max(now, 0) // a count it leaves out, or writes as no count, is 0
		was := 0.0
		if i < len(before) {
			was, _ = run.Num(before[i])
		}
		running[i], grown[i] = run.Number(strconv.Itoa(now)), max(0, now-int(was))
	}
	cursor.Set("total", max(previous, total))
	cursor.Set("running", running)
	spend := Spend{At: at, Event: filepath.Base(cursor.Str("source")) + ":" + strconv.Itoa(total), Tokens: max(0, total-previous), Model: cursor.Get("model")}
	if known {
		// as input, cache write, cache read and output, the input less what was cached or
		// written to the cache
		fresh, cached, written, output := grown[0], grown[1], grown[2], grown[3]
		spend.Counts = []int{max(0, fresh-cached-written), written, cached, output}
	}
	return spend, true
}

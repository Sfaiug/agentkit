package harness

import (
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// claudeKilledCounts is the counts of a turn killed before Claude Code wrote its result, by
// model, claude.py `_transcript_usage`: its own messages, each at the most a line counts it, of
// all its stream's lines and those its session's transcripts hold from its harness receipt to
// its last event; false where it is missing either or none is found.  The stream counts a
// message's input and cache but only its first chunk of output; the transcript keeps its final
// counts.  Python also names the session where a transcript's line counted, which the session's
// next turn's share needs; Go names none yet, so these count this turn alone.
func claudeKilledCounts(out string, init *run.Object) (any, []Counts, bool) {
	events := filepath.Join(out, "events.jsonl")
	began, err := os.Stat(filepath.Join(out, "harness"))
	ended, err2 := os.Stat(events)
	if err != nil || err2 != nil {
		return nil, nil, false
	}
	// st_mtime as Python's stat reckons it: nanoseconds since 1970 overflow a float's precision,
	// so dividing them misplaces a message stamped exactly on either end of the span
	seconds := func(info os.FileInfo) float64 {
		return float64(info.ModTime().Unix()) + float64(info.ModTime().Nanosecond())*1e-9
	}
	from, to := seconds(began), seconds(ended)
	var account any
	if text, err := os.ReadFile(filepath.Join(out, "account")); err == nil {
		account = string(text)
	}
	record := run.Fields("account", account, "cwd", init.Get("cwd"), "conversation", init.Get("session_id"))
	type line struct {
		path string
		n    int
	}
	messages, order := map[any]Spend{}, []any{}
	for _, path := range append([]string{events}, claudeTokenSources(record)...) {
		lines, _ := jsonLines(path, nil)
		for n, value := range lines {
			entry, _ := value.(*run.Object)
			if entry == nil {
				continue
			}
			// the stream's events are the turn's own, and carry no time
			spend, counts := claudeTokenUsage(entry, nil)
			if !counts || path != events && (spend.At < from || spend.At > to) {
				continue
			}
			var key any = spend.Event
			if spend.Event == "" {
				key = line{path, n}
			}
			// a message's lines repeat it; the one counting most holds its final counts
			if kept, seen := messages[key]; !seen {
				order = append(order, key)
			} else if spend.Tokens <= kept.Tokens {
				continue
			}
			messages[key] = spend
		}
	}
	var totals []Counts
	at := map[any]int{}
	for _, key := range order {
		spend := messages[key]
		if _, seen := at[spend.Model]; !seen {
			at[spend.Model] = len(totals)
			totals = append(totals, Counts{Model: spend.Model})
		}
		for kind, count := range spend.Counts {
			totals[at[spend.Model]].Spent[kind] += int64(count)
		}
	}
	return nil, totals, len(totals) > 0
}

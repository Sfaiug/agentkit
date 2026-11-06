package doctor

import (
	"fmt"
	"math"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// gateLine is the gates line, Python's watch.gates_health: each gate holding a live run now, else
// how long since history last saw it hold one.  False where a record or history.db is one Go
// cannot read.
func gateLine() (string, bool) {
	now := float64(time.Now().UnixNano()) / 1e9
	last, read := history.GateHolds()
	if !read {
		return "", false
	}
	holding := map[string]bool{}
	behind := run.SlotQueue()
	if len(behind) > 0 {
		behind = behind[1:]
	}
	if !run.Every(func(_ string, record *run.Object) bool {
		if !run.ProcessActive(record) {
			return true
		}
		if record.Str("state") == "queued" && record.Truthy("slot_waiting") {
			kind := record.Str("slot_wait_kind")
			// a run behind the first in line waits for its turn, not for room
			if slices.Contains(behind, record.Str("run_id")) {
				kind = "count"
			}
			if name, ok := history.SlotGates[kind]; ok {
				holding[name] = true
			}
		}
		if run.GateTurnNote(record) != "" {
			holding["suite turns"] = true
		}
		return true
	}) {
		return "", false
	}
	// a line's checker marks no run record: its wait file is locked only while it waits
	waits, _ := filepath.Glob(filepath.Join(run.Runs(), ".landing-wait-*"))
	if slices.ContainsFunc(waits, lock.Held) {
		holding["suite turns"] = true
	}
	var parts []string
	for _, name := range []string{"admission", "suite turns", "memory"} {
		at, held := last[name]
		status := "never held"
		if holding[name] {
			status = "holding now"
		} else if held {
			days := max(0, int(math.Floor((now-at)/86400)))
			noun := "days"
			if days == 1 {
				noun = "day"
			}
			when := time.Unix(int64(math.Floor(at)), 0).Format("2006-01-02 15:04")
			status = fmt.Sprintf("%d %s idle, last held %s", days, noun, when)
		}
		parts = append(parts, name+" "+status)
	}
	return strings.Join(parts, " · "), true
}

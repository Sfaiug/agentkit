package tick

import (
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A going loop with recent output needs no stall recovery, its output being its run folder's
// last write (watch.stall_clock).
func notSilent(dir string, record *run.Object) bool {
	// a dead loop's silence is measured too: only a live one is asked whether the host froze it
	pid, _ := record.Int("pid")
	alive := run.ProcessActive(record)
	if record.Truthy("frozen_since") || alive && host.Frozen(pid) {
		return false
	}
	minutes := float64(run.SilenceMinutes)
	if record.Has("silence_minutes") {
		var known bool
		if minutes, known = dated(record, "silence_minutes"); !known || minutes <= 0 {
			return false
		}
	}
	latest := run.FirstNumber(record, "thawed_at")
	if wait := record.Dict("transient_wait"); wait != nil && run.Equal(wait.Get("pid"), record.Get("pid")) {
		latest = max(latest, run.FirstNumber(wait, "until"))
	}
	if alive && record.Truthy("delivery_wait") && run.Equal(record.Get("delivery_wait"), record.Get("pid")) {
		return true
	}
	// what a live loop removes as it is walked, a box it takes down, is no sign it went silent
	return epoch(time.Now())-max(latest, run.LastWrite(dir)) < minutes*60
}

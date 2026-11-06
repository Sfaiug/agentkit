package tick

import (
	"os"
	"strings"
	"time"

	"agentkit/internal/run"
)

// Login resume asks authentication only of a run parked on it.
func noLoginResume() bool {
	return run.Every(func(_ string, record *run.Object) bool { return record.Str("state") != "waiting_login" })
}

// Seat health reads parked logins and recovery alongside the seat's own evidence.
func noRunHealthWork() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		_, sweep := run.Reap(record)
		return record.Str("state") != "waiting_login" && !sweep
	})
}

func dated(record *run.Object, key string) (float64, bool) {
	if _, boolean := record.Get(key).(bool); boolean {
		return 0, false
	}
	return record.Num(key)
}

func resumeOrdered(record *run.Object, now float64) bool {
	at, ok := dated(record, "stall_resume_at")
	return ok && 0 <= now-at && now-at < 600
}

func launchGrace(record *run.Object, now float64) bool {
	if record.Str("state") != "queued" || !record.Truthy("launch_pending") && record.Truthy("process_identity") {
		return false
	}
	at := run.FirstNumber(record, "queued_at", "started_at")
	return now-at < 30
}

// Dead loops leave live processes, launches in flight, and a death already parked alone.
func noDeadLoops() bool {
	now := epoch(time.Now())
	return run.Every(func(_ string, record *run.Object) bool {
		deaths := record.List("deaths")
		if !run.Active(record) && !(record.Str("state") == "interrupted" && len(deaths) > 0) {
			return true
		}
		if len(deaths) > 0 {
			if last, ok := deaths[len(deaths)-1].(*run.Object); ok && last.Truthy("parked") {
				return true
			}
		}
		return launchGrace(record, now) || resumeOrdered(record, now) || run.ProcessActive(record)
	})
}

// Silent running loops need Python's stall clocks; a parked run only needs its refused notice.
func noStallRecovery() bool {
	return run.Every(func(dir string, record *run.Object) bool {
		switch record.Str("state") {
		case "running":
			return notSilent(dir, record) || resumeOrdered(record, epoch(time.Now())) && !run.ProcessActive(record)
		case "queued":
			return !record.Truthy("slot_waiting") || run.ProcessActive(record) || resumeOrdered(record, epoch(time.Now()))
		case "stalled":
			return record.Truthy("stalled_notified")
		}
		return true
	})
}

// Exhaustion's window and reviewer selection still belong to Python.
func noExhaustedResume() bool {
	return configured() && os.Getenv("AGENTKIT_SESSION") == "" && run.Every(func(_ string, record *run.Object) bool {
		return record.Str("state") != "exhausted" || record.Truthy("replaced") ||
			!record.Truthy("quota_dry") && !strings.Contains(record.Str("error"), "API/transport errors")
	})
}

func directory(path string) bool {
	info, err := os.Stat(path)
	return path != "" && err == nil && info.IsDir()
}

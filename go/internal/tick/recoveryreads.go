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

func launchGrace(record *run.Object, now float64) bool {
	if record.Str("state") != "queued" || !record.Truthy("launch_pending") && record.Truthy("process_identity") {
		return false
	}
	at := run.FirstNumber(record, "queued_at", "started_at")
	return now-at < 30
}

// A dry tick reads whether the dead-loop pass would say anything, which Python's says.
func noDeadLoops() bool {
	now := epoch(time.Now())
	return run.Every(func(_ string, record *run.Object) bool {
		return !deadLoop(record, now) || run.ResumeOrdered(record, now)
	})
}

// Silent running loops need Python's stall clocks, and a slot waiter that died its restart; a
// parked run's notice is tellParked's.
func noStallRecovery() bool {
	return run.Every(func(dir string, record *run.Object) bool {
		switch record.Str("state") {
		case "running":
			return notSilent(dir, record) || run.ResumeOrdered(record, epoch(time.Now())) && !run.ProcessActive(record)
		case "queued":
			return !record.Truthy("slot_waiting") || run.ProcessActive(record) || run.ResumeOrdered(record, epoch(time.Now()))
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

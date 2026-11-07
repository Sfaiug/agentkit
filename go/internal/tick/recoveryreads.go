package tick

import (
	"os"
	"time"

	"agentkit/internal/run"
)

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

// The tick's resume of an exhausted run picks within a seat's own selection where the tick runs
// in one, which Go does not read yet.
func unseated() bool { return os.Getenv("AGENTKIT_SESSION") == "" }

// A dry tick hands over wherever a run waits on the tick's resume, which Python's says it would make.
func noExhaustedResume() bool {
	return run.Every(func(_ string, record *run.Object) bool { return run.ExhaustedWait(record) == "" })
}

func directory(path string) bool {
	info, err := os.Stat(path)
	return path != "" && err == nil && info.IsDir()
}

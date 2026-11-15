package tick

import (
	"os"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Seat health reads parked logins and recovery alongside the seat's own evidence, and stalls the
// seat whose going run a login keeps refusing (watch.health).
func noRunHealthWork() bool {
	return run.Every(func(dir string, record *run.Object) bool {
		if _, sweep := run.Reap(record); sweep || record.Str("state") == "waiting_login" {
			return false
		}
		login, known := seat.Refusing(dir, record)
		return known && login == ""
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
	return run.Every(func(dir string, record *run.Object) bool { return !DeadLoop(dir, record, now) })
}

// The tick's resume of an exhausted run picks within a seat's own selection where the tick runs
// in one, which Go does not read yet.
func unseated() bool { return os.Getenv("AGENTKIT_SESSION") == "" }

func directory(path string) bool {
	info, err := os.Stat(path)
	return path != "" && err == nil && info.IsDir()
}

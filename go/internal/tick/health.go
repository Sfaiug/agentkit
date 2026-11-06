package tick

import (
	"fmt"
	"os"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// Health is the line `ak doctor` and a dry tick print, as Python's tick_health: whether a tick
// holds the lock, its pid and for how long, when the last tick ended, and how near the log is to
// the size it is rolled at. Stuck is whether the tick reads as hung: nothing has ended within 30
// minutes, or a holder has held the lock that long. False where watch.json is what Go cannot read.
func Health() (line string, stuck, ok bool) {
	state, ok := loadState()
	if !ok {
		return "", false, false
	}
	held := "lock free"
	if lock.Held(lockPath()) {
		pid, began := holder(lockPath())
		holding := max(0, time.Since(began))
		held = fmt.Sprintf("lock held by pid %s for %d min", pid, int(holding/time.Minute))
		stuck = holding >= hung
	}
	ended, silent := lastEnded(state.Dict("tick"))
	var size int64
	if info, err := os.Stat(logPath()); err == nil {
		size = info.Size()
	}
	return fmt.Sprintf("%s · %s · %s %.1f MB of %d MB", held, ended, logName, float64(size)/(1<<20), logMax>>20), stuck || silent, true
}

// lastEnded is what the line says of the record the last tick left, as Python's tick_ended, and
// whether that silence is a hang. A record no tick wrote says nothing ended.
func lastEnded(record *run.Object) (string, bool) {
	const none = "no tick has ended yet"
	if record == nil {
		return none, true
	}
	slowest := record.Dict("slowest")
	ended, hasEnd := record.Num("ended_at")
	started, hasStart := record.Num("started_at")
	if slowest == nil || !hasEnd || !hasStart || !slowest.Has("pass") || !slowest.Has("seconds") {
		return none, true
	}
	age := epoch(time.Now()) - ended
	said := fmt.Sprintf("ended %s ago, took %.1f s, slowest %s %s s", terminal.FormatAge(age), ended-started,
		run.Text(slowest.Get("pass")), run.Text(slowest.Get("seconds")))
	if age < hung.Seconds() {
		return said, false
	}
	return said + " · no tick has ended within " + terminal.FormatAge(hung.Seconds()), true
}

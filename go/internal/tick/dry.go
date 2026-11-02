package tick

import (
	"fmt"
	"io"
	"os"
	"runtime"
	"time"

	"agentkit/internal/gh"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Dry is `ak watch --dry-run` on a home where no pass has anything to act on, as Python's
// watch.main runs one: the line on who holds the tick lock, that no tick has ended and how big
// the log is, then why the GitHub passes are skipped; it writes nothing. False, with nothing
// printed, wherever a pass would find something or gh says who is logged in, and on Windows, as
// Overlap.
func Dry(out io.Writer) bool {
	if runtime.GOOS == "windows" {
		return false
	}
	health := healthLine()
	if !idle(true) {
		return false
	}
	value, why, err := gh.JSON(run.Runs(), "api", "user")
	if err != nil || login(value) != "" {
		return false
	}
	line, _ := unanswered(why)
	fmt.Fprintln(out, health)
	fmt.Fprintln(out, line)
	return true
}

// healthLine is whether a tick holds the lock, its pid and for how long, that no tick has ended,
// and how near the log is to the size it is rolled at. The ending goes unread: a dry tick answers
// only where no tick has kept watch.json (stateless), and a tick that ended kept it.
func healthLine() string {
	held := "lock free"
	if lock.Held(lockPath()) {
		pid, holding := holder(lockPath())
		held = fmt.Sprintf("lock held by pid %s for %d min", pid, int(holding/time.Minute))
	}
	var size int64
	if info, err := os.Stat(logPath()); err == nil {
		size = info.Size()
	}
	return fmt.Sprintf("%s · no tick has ended yet · %s %.1f MB of %d MB", held, logName, float64(size)/(1<<20), logMax>>20)
}

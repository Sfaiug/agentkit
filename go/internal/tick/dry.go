package tick

import (
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Dry is `ak watch --dry-run` on a home where no pass has anything to act on, as Python's
// watch.main runs one: the line on who holds the tick lock and how big the log is, then why the
// GitHub passes are skipped; it writes nothing. False, with nothing printed, wherever a pass
// would find something or gh says who is logged in, and on Windows, as Overlap.
func Dry(out io.Writer) bool {
	if runtime.GOOS == "windows" {
		return false
	}
	health := healthLine()
	for _, idle := range passes {
		if !idle() {
			return false
		}
	}
	value, why, err := gh.JSON(run.Runs(), "api", "user")
	if user, _ := value.(*run.Object); err != nil || user != nil && user.Str("login") != "" {
		return false
	}
	if why == "" {
		why = "gh api user failed"
	}
	// gh's advice runs to several lines; one line is the whole point here
	words := []rune(strings.Join(strings.FieldsFunc(why, config.Space), " "))
	reason := string(words[:min(len(words), 160)])
	line := "WARN GitHub is unavailable; PR checks skipped (" + reason + ")"
	if gh.LoggedOut(reason) {
		line = "gh is not logged in; PR checks skipped (" + reason + ")"
	}
	fmt.Fprintln(out, health)
	fmt.Fprintln(out, line)
	return true
}

// healthLine is whether a tick holds the lock, its pid and for how long, and how near the log is
// to the size it is rolled at.
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
	return fmt.Sprintf("%s · %s %.1f MB of %d MB", held, logName, float64(size)/(1<<20), logMax>>20)
}

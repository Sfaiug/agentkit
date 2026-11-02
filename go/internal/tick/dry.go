package tick

import (
	"fmt"
	"io"
	"runtime"

	"agentkit/internal/gh"
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
	health, _, ok := Health()
	if !ok || !idle(true) {
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

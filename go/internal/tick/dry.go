package tick

import (
	"fmt"
	"io"
	"runtime"

	"agentkit/internal/config"
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
	if !ok || !idle() {
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

// idle is whether watch.json and every row a dry tick reads say there is nothing to act on, read
// with nothing written. The state folder comes first: the rows' seat records are listed from it.
func idle() bool {
	if state, ok := loadState(); !ok || !quiet(state) || !config.Listable(statePath("")) {
		return false
	}
	for _, each := range table(&ticking{dry: true}) {
		if each.dry && each.idle != nil && !each.idle() {
			return false
		}
	}
	return true
}

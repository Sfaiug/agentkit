package tick

import (
	"bytes"
	"fmt"
	"io"
	"runtime"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// Dry is `ak watch --dry-run`, as Python's watch.main runs one: the line on who holds the tick
// lock, that no tick has ended and how big the log is, what each row would do, then why the
// GitHub passes are skipped; it writes nothing. It runs the tick's own rows with its dry switch
// and keeps what they say until each has proved Go's. False, with nothing printed, wherever a row
// finds what Go does not carry or gh says who is logged in, and on Windows, as Overlap.
func Dry(out io.Writer) bool {
	if runtime.GOOS == "windows" {
		return false
	}
	health, _, ok := Health()
	// the state folder comes first: the rows' seat records are listed from it
	state, known := loadState()
	if !ok || !known || !quiet(state) || !config.Listable(statePath("")) {
		return false
	}
	var preview bytes.Buffer
	// a dry step sends nothing, so has nothing of its own to say on stderr
	t := &ticking{state: state, log: newLog(&preview, io.Discard), clock: time.Now, dry: true}
	if !t.through(table(t)) {
		return false
	}
	value, why, err := gh.JSON(run.Runs(), "api", "user")
	if err != nil || login(value) != "" {
		return false
	}
	line, _ := unanswered(why)
	fmt.Fprintln(out, health)
	preview.WriteTo(out)
	fmt.Fprintln(out, line)
	return true
}

package tick

import (
	"bytes"
	"fmt"
	"io"
	"runtime"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Dry is `ak watch --dry-run`, as Python's watch.main runs one: the line on who holds the tick
// lock, that no tick has ended and how big the log is, then what each row and GitHub pass would
// do; it writes nothing, its reads keeping nothing they follow. It runs the tick's own rows and
// GitHub passes with its dry switch, their looks one dry look (seat.DryTick), and keeps what they
// say until each has proved Go's. It says where it leaves the dry run to Python, with nothing
// printed, as Carry does, and nothing where it does not.
func Dry(out io.Writer) (left string) {
	if runtime.GOOS == "windows" {
		return beforePasses
	}
	defer harness.KeepNothing()()
	defer seat.DryTick()()
	health, _, ok := Health()
	// the state folder comes first: the rows' seat records are listed from it
	state, known := loadState()
	if !ok || !known || !quiet(state) || !config.Listable(statePath("")) {
		return beforePasses
	}
	var preview bytes.Buffer
	// a dry step sends nothing, so has nothing of its own to say on stderr
	t := &ticking{state: state, log: newLog(&preview, io.Discard), clock: time.Now, dry: true}
	if !t.through(table(t)) {
		return t.left
	}
	value, why, err := gh.JSON(run.Runs(), "api", "user")
	if err != nil {
		return githubUser
	}
	// a dry tick says no pass's time
	if t.github(value, why, 0) != nil {
		return t.left
	}
	fmt.Fprintln(out, health)
	preview.WriteTo(out)
	return ""
}

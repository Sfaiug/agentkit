package gitcall

import (
	"time"

	"agentkit/internal/host"
)

// ceiling is the most time a git asking no remote gets, Python's LOCAL_CEILING.
const ceiling = time.Hour

// base is CapSeconds as a limit, and hostLoad the host's load and cores, each a variable so a
// test can give its own.
var (
	base     = CapSeconds * time.Second
	hostLoad = host.Load
)

// defaultCap is a git's limit where its caller sets none, Python's tool_run: base for one that
// asks a remote, and for any other base times the host's load per core, read as it starts,
// where that is over one, and the ceiling at most: a git waiting its turn for a core is not
// hung.  (12 Nov 2026: at 16 times its cores' load, killing such gits at 120 s stopped seven
// runs in a morning.)
func defaultCap(args []string) time.Duration {
	if retried(args) {
		return base
	}
	load, cores := hostLoad()
	return time.Duration(min(float64(ceiling), float64(base)*max(1, load/float64(cores))))
}

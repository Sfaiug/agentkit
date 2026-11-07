package cli

import (
	"io"
	"time"

	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// orchAgain answers `ak orch NAME` for a seat that is there, as Python's orch.main does, and
// whether one is: tmux holds it, or its record does and no model is named, the one way to ask for
// a new seat by its name.  An open Python's maintenance would find work on the way in for is
// Python's; a dry run has none.
func orchAgain(name string, dryRun, forced bool, out, errOut io.Writer) (int, bool) {
	if name == "" || !seat.There(name, forced) {
		return 0, false
	}
	if !dryRun && !seat.Tidy(time.Now()) {
		return notImplemented(errOut, "orch"), true
	}
	known, err := seat.Reopen(name, seat.How{DryRun: dryRun, Terminal: terminal.Attachable(), Owner: true}, out, errOut)
	return orchAnswer("orch", "", known, err, out, errOut), true
}

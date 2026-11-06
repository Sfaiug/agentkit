package cli

import (
	"io"
	"os"
	"os/signal"
	"syscall"

	"agentkit/internal/harness"
	"agentkit/internal/seat"
)

// status is a seat's status line, `ak hook status`, as the status script under hooks/ is
// Python's: the render's JSON handed on as it came, to the owner's own status command where the
// line pipes it on, then what it says the conversation runs on written down, and the seat looked
// at again at once where that changed what was.  The report belongs to the render's
// conversation, never the seat's launch name.  A render outside any seat or in a worker writes
// nothing.
func status(payload []byte, out io.Writer) int {
	// an owner's command that never reads its stdin closes the pipe, which ends no report
	signal.Notify(make(chan os.Signal, 1), syscall.SIGPIPE)
	out.Write(payload)
	if os.Getenv("AGENTKIT_SESSION") != "" && os.Getenv("AK_RUN_ROLE") != "worker" && harness.Report(payload) {
		seat.LookSoon(nil)
	}
	return 0
}

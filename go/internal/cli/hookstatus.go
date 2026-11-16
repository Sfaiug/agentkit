package cli

import (
	"io"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/seat"
	"agentkit/internal/usage"
)

// status is a seat's status line, `ak hook status`, as the status script under hooks/ is
// Python's: the render's JSON handed on as it came, to the owner's own status command where the
// line pipes it on, then what it says the conversation runs on written down, and the seat looked
// at again at once where that changed what was.  A render whose limits of its login read otherwise
// than its conversation's note holds them hands them in, with the moment it began, off the
// harness's path (`meters`).  The report belongs to the render's conversation, never the seat's
// launch name.  A render outside any seat or in a worker writes nothing.
func status(payload []byte, name string, began float64, out io.Writer) int {
	// an owner's command that never reads its stdin closes the pipe, which ends no report
	signal.Notify(make(chan os.Signal, 1), syscall.SIGPIPE)
	out.Write(payload)
	launched, login := os.Getenv("AGENTKIT_SESSION"), os.Getenv("AGENTKIT_ACCOUNT")
	if launched == "" || os.Getenv("AK_RUN_ROLE") == "worker" {
		return 0
	}
	conversation, windows := harness.Limits(name, payload)
	if program, err := os.Executable(); err == nil && !harness.Noted(conversation, login, windows) {
		handIn := exec.Command(program, append([]string{"hook", "meters", launched, conversation, login,
			strconv.FormatFloat(began, 'f', -1, 64)}, windows...)...)
		handIn.Env = host.Unmarked(os.Environ())
		host.Detach(handIn)
		if handIn.Start() == nil {
			handIn.Process.Release()
		}
	}
	if harness.Report(payload) {
		seat.LookSoon(nil)
	}
	return 0
}

// meters is a render's hand-in, `ak hook meters <seat> <conversation> <login> <moment>
// <window>...`, Python's watch.hook_meters: the windows that changed from its conversation's note
// become its login's reading at the render's moment, of the provider of the model the seat holds.
func meters(launched, conversation, login, moment string, windows []string) int {
	began, err := strconv.ParseFloat(moment, 64)
	if err != nil {
		return 0
	}
	model := config.SeatModel(launched)
	if changed := harness.Note(conversation, login, began, windows); model.Harness != "" && len(changed) > 0 {
		usage.Reported(model.Provider, login, harness.StatusMeters(model.Harness, changed), began)
	}
	return 0
}

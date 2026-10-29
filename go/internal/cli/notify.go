package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/notify"
)

func init() { commands["notify needs"] = notifyNeeds }

// notifyNeeds decides in notify.main's order: the arguments (validateNotify), the worker, the
// question's shape, then the seat.  It carries out a dry run; a real ask, and a seat's ask for
// itself, whose turn decides it, come in a later milestone.
func notifyNeeds(args []string, out, errOut io.Writer) int {
	asked, _ := parseNeeds(args) // validateNotify refused what it cannot read
	if notify.Suppressed(asked.dryRun, out) {
		return 0 // before the question's shape: a worker asks nothing
	}
	if err := notify.AsksFirst(asked.question); errors.Is(err, notify.ErrUnread) {
		return notImplemented(errOut, "notify needs")
	} else if err != nil {
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	}
	// a seat name Go cannot read is left to Python, as is a question
	if !utf8.ValidString(os.Getenv("AGENTKIT_SESSION")) || !utf8.ValidString(asked.session) {
		return notImplemented(errOut, "notify needs")
	}
	own, _, err := config.CurrentSession()
	seat := ""
	if err == nil && (asked.session != "" || own != "" && asked.named) {
		seat, _, err = config.ResolveSession(asked.session)
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	}
	if own != "" && (!asked.named || seat == own) {
		return notImplemented(errOut, "notify needs") // a seat asking for itself: its turn decides
	}
	if !asked.dryRun && seat == "" {
		fmt.Fprintln(errOut, "ak notify: notify needs a session: use --session NAME")
		return 2
	}
	if !asked.dryRun {
		return notImplemented(errOut, "notify needs")
	}
	if err := notify.DryRun(seat, asked.question, out, errOut); err != nil {
		return notImplemented(errOut, "notify needs")
	}
	return 0
}

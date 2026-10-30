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

func init() {
	commands["notify"] = notifyCheck
	commands["notify needs"] = notifyNeeds
}

// notifyCheck answers --check, all validateNotify leaves `ak notify` without a sub-verb.
func notifyCheck(_ []string, out, errOut io.Writer) int {
	code, err := notify.Check(out, errOut)
	if errors.Is(err, notify.ErrUnread) {
		return notImplemented(errOut, "notify --check")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	}
	return code
}

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
	// a seat asking for itself is left to Python before either name is resolved: its turn decides
	own := os.Getenv("AGENTKIT_SESSION")
	if own != "" && (!asked.named || config.Fold(asked.session) == config.Fold(own)) {
		return notImplemented(errOut, "notify needs")
	}
	// a seat name Go cannot read is left to Python, as is a question
	if !utf8.ValidString(own) || !utf8.ValidString(asked.session) {
		return notImplemented(errOut, "notify needs")
	}
	current, _, err := config.CurrentSession()
	seat := ""
	if err == nil && (asked.session != "" || current != "") {
		seat, _, err = config.ResolveSession(asked.session)
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	}
	if current != "" && seat == current {
		return notImplemented(errOut, "notify needs") // itself, by a name it had before a rename
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

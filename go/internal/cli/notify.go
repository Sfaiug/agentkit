package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/notify"
)

func init() {
	commands["notify needs"] = notifyNeeds
	commands["notify"] = notifyCheck // validateNotify leaves it only --check
}

// notifyCheck asks the configured webhook whether it is live: 0 for a 200, 1 for any other
// answer or no answer, and 2 for no webhook configured.
func notifyCheck(_ []string, out, errOut io.Writer) int {
	live, err := notify.Check(out, errOut)
	switch {
	case errors.Is(err, notify.ErrUnread):
		return notImplemented(errOut, "notify --check")
	case err != nil:
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	case live:
		return 0
	}
	return 1
}

// notifyNeeds decides in notify.main's order: the arguments (validateNotify), the worker, the
// question's shape, then the seat.  It carries out a dry run, and an ask for another seat where
// notify.Ask knows its word; a seat's ask for itself, whose turn decides it, comes in a later
// milestone.
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
	seat, record := "", map[string]any(nil)
	if err == nil && (asked.session != "" || current != "") {
		seat, record, err = config.ResolveSession(asked.session)
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
		code, decided := notify.Ask(seat, record, strings.TrimFunc(asked.question, config.Space), out, errOut)
		if !decided {
			return notImplemented(errOut, "notify needs")
		}
		return code
	}
	if err := notify.DryRun(seat, asked.question, out, errOut); err != nil {
		return notImplemented(errOut, "notify needs")
	}
	return 0
}

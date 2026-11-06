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
	"agentkit/internal/run"
	"agentkit/internal/seat"
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
// question's shape, then the seat.  It carries out a dry run, an ask for another seat where
// notify.Ask knows its word, and a seat's ask for itself, kept back for its turn's end.
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
	own := os.Getenv("AGENTKIT_SESSION")
	// a seat name Go cannot read is left to Python, as is a question
	if !utf8.ValidString(own) || !utf8.ValidString(asked.session) {
		return notImplemented(errOut, "notify needs")
	}
	current, record, err := config.CurrentSession()
	name := current
	if err == nil && asked.session != "" {
		name, record, err = config.ResolveSession(asked.session)
	}
	// a seat asking for itself is left to Python where its own record cannot say what it runs
	if err != nil && own != "" && (!asked.named || config.Fold(asked.session) == config.Fold(own)) {
		return notImplemented(errOut, "notify needs")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak notify: %s\n", err)
		return 2
	}
	if current != "" && name == current {
		return askItself(name, asked, errOut)
	}
	if !asked.dryRun && name == "" {
		fmt.Fprintln(errOut, "ak notify: notify needs a session: use --session NAME")
		return 2
	}
	if !asked.dryRun {
		code, decided := notify.Ask(name, record, strings.TrimFunc(asked.question, config.Space), seat.AskedWord, out, errOut)
		if !decided {
			return notImplemented(errOut, "notify needs")
		}
		return code
	}
	if err := notify.DryRun(name, asked.question, out, errOut); err != nil {
		return notImplemented(errOut, "notify needs")
	}
	return 0
}

// askItself is a seat's own question as notify.main and shaped take it, its dry run left to Python:
// one its plan's end would refuse is refused, and the rest is kept back for the end of the turn it is
// asked in, as every seat its harness names does (`watch.keeps_back`).
func askItself(name string, asked needs, errOut io.Writer) int {
	refused, err := seat.QuestionRefused(name)
	if err != nil || asked.dryRun || config.SeatHarness(name) == "" {
		return notImplemented(errOut, "notify needs")
	}
	if refused != "" {
		fmt.Fprintf(errOut, "ak notify: %s\n", refused)
		return 2
	}
	err = seat.Keep(name, strings.TrimFunc(asked.question, config.Space))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return notImplemented(errOut, "notify needs")
	}
	if err != nil {
		fmt.Fprintf(errOut, "WARN could not record what %s is doing: %v\n", name, err)
	}
	return 0
}

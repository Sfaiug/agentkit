package cli

import (
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/handover"
	"agentkit/internal/host"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func init() { commands["orch"] = orchOpen }

const orchUsage = "usage: ak orch [name] [--model NAME] [--workers A,B] [--dry-run] | ak orch list [--why] | ak orch why NAME | ak orch stop <name> | ak orch rename [--auto] [OLD] NEW | ak orch project [<seat>] <checkout>"

func validateOrch(args []string) string {
	if len(args) > 0 {
		rest := args[1:]
		switch args[0] {
		case "list":
			if len(rest) > 0 && !(len(rest) == 1 && rest[0] == "--why") {
				return commandhelp.Usage("orch list")
			}
			return ""
		case "ended", "front":
			// tmux's hooks' hidden verbs, which read their own words (orchOpen)
			return ""
		case "why", "rules", "stop", "check", "look", "pair":
			if len(rest) != 1 {
				if args[0] == "stop" {
					return "usage: ak orch stop <name>"
				}
				return commandhelp.Usage("orch " + args[0])
			}
			if args[0] == "rules" && os.Getenv("AGENTKIT_SESSION") == "" {
				return "ak orch rules belongs to a seat; run it inside one"
			}
			return ""
		case "rename", "project":
			verb := args[0]
			if verb == "rename" {
				rest = without(rest, "--auto")
			}
			if len(rest) < 1 || len(rest) > 2 {
				if verb == "project" {
					return "usage: ak orch project [<seat>] <checkout>"
				}
				return commandhelp.Usage("orch rename")
			}
			if len(rest) == 1 && os.Getenv("AGENTKIT_SESSION") == "" {
				if verb == "project" {
					return "ak orch project <checkout> files the session it runs in, and this is not one; use ak orch project <seat> <checkout>"
				}
				return "ak orch rename <new> renames the session it runs in, and this is not one; use ak orch rename <old> <new>"
			}
			if verb == "rename" && strings.HasPrefix(rest[len(rest)-1], "-") {
				return fmt.Sprintf("not a session name: %s", commandhelp.Quote(rest[len(rest)-1]))
			}
			return ""
		}
	}
	name := false
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--dry-run":
		case "--model", "--workers":
			if i+1 == len(args) {
				if arg == "--model" {
					return "--model needs a model name"
				}
				return "--workers needs a comma-separated list of model names"
			}
			i++
		default:
			if strings.HasPrefix(arg, "-") || name {
				return fmt.Sprintf("%s  (got %s)", orchUsage, commandhelp.Quote(arg))
			}
			name = true
		}
	}
	if err := config.Check(); err != nil {
		return err.Error()
	}
	return ""
}

// orchOpen refuses an open nobody typed, as Python's main does: only a person opens a seat.  It
// answers only where Python's maintenance finds nothing to tidy on the way in; a seat that is
// there is orchAgain's, a person's open and a dry run are orchNew's, pane-died's `ended` brings
// back a seat whose harness ended, and the client hooks' `front` puts the seats a client is in
// first.
func orchOpen(args []string, out, errOut io.Writer) int {
	// validateOrch reads nothing after `ended` or `front`: they read their own
	if len(args) > 0 && args[0] == "ended" {
		handover.Runs("orch ended")
		return orchEnded(args[1:], out, errOut)
	}
	if len(args) > 0 && args[0] == "front" {
		host.Front()
		return 0
	}
	name, dryRun, flags := "", false, map[string]string{}
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dry-run":
			dryRun = true
		case "--model", "--workers":
			flags[args[i]] = args[i+1]
			i++
		default:
			name = config.SessionName(args[i])
		}
	}
	if code, there := orchAgain(name, dryRun, len(flags) > 0, out, errOut); there {
		return code
	}
	if dryRun {
		return orchNew(name, flags, true, out, errOut)
	}
	tidy := seat.Tidy(time.Now())
	// a seat name CurrentSession refuses is Python's
	seat, _, err := config.CurrentSession()
	typed := terminal.TypedHere()
	if err != nil || !tidy {
		return notImplemented(errOut, "orch")
	}
	// a terminal a seat made is not a person's
	if typed && seat == "" {
		return orchNew(name, flags, false, out, errOut)
	}
	// Python's maintenance makes ak's folders before it refuses; an open makes them once it is Go's
	if config.EnsureDirs() != nil {
		return notImplemented(errOut, "orch")
	}
	how := "a new seat opens only from a terminal (the menu's n, or `ak orch NAME` typed there)"
	if typed {
		how = "a seat opens no seat: only the owner does, with the menu's n"
	}
	seat = "no seat name given"
	if name != "" {
		seat = "no seat named " + name
	}
	fmt.Fprintf(errOut, "ak orch: %s; %s\n%s\n", seat, how, orchUsage)
	return 2
}

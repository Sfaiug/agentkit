package cli

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
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
		case "ended":
			// tmux's pane-died hook's hidden verb, Python's alone (orchOpen)
			return ""
		case "why", "rules", "stop":
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
// answers only where Python's maintenance finds nothing to tidy on the way in; a dry run, a
// person's open and pane-died's `ended` are Python's.
func orchOpen(args []string, _, errOut io.Writer) int {
	name, dryRun := "", false
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dry-run":
			dryRun = true
		case "--model", "--workers":
			i++
		default:
			name = config.SessionName(args[i])
		}
	}
	how := "a new seat opens only from a terminal (the menu's n, or `ak orch NAME` typed there)"
	if terminal.TypedHere() {
		// a terminal a seat made is not a person's; a person's open is Python's, as is a seat
		// name CurrentSession refuses
		if seat, _, _ := config.CurrentSession(); seat == "" {
			return notImplemented(errOut, "orch")
		}
		how = "a seat opens no seat: only the owner does, with the menu's n"
	}
	if dryRun || len(args) > 0 && args[0] == "ended" || !tidy() || config.EnsureDirs() != nil {
		return notImplemented(errOut, "orch")
	}
	seat := "no seat name given"
	if name != "" {
		seat = "no seat named " + name
	}
	fmt.Fprintf(errOut, "ak orch: %s; %s\n%s\n", seat, how, orchUsage)
	return 2
}

// tidy is whether Python's maintenance finds nothing to tidy: no seat file, no run, no session
// on ak's server but its control one, and none ak opened on the default server.  A folder
// missing holds nothing; one Go cannot read may hold anything.
func tidy() bool {
	for place, prefix := range map[string]string{"state": "session-", "runs": ""} {
		entries, err := os.ReadDir(filepath.Join(config.Home(), place))
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return false
		}
		for _, entry := range entries {
			if strings.HasPrefix(entry.Name(), prefix) {
				return false
			}
		}
	}
	if len(tmux.Sessions(tmux.Own())) > 0 {
		return false
	}
	for _, session := range tmux.Sessions(tmux.Default) {
		if session.Mark == "1" {
			return false
		}
	}
	return true
}

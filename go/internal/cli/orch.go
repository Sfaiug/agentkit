package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

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

func init() { commands["orch"] = orch }

// orch is `ak orch [name]`, in Python's order: its arguments, then (outside a dry run) the reap
// on the way in, a seat by that name, the terminal and the models.  Go refuses an open nobody
// typed and previews a new seat; a reap that would act, an attach, a resume, an open and a
// question it leaves to Python.
func orch(args []string, out, errOut io.Writer) int {
	name, flags := "", map[string]string{}
	for i := 0; i < len(args); i++ {
		if args[i] == "--model" || args[i] == "--workers" {
			flags[args[i]] = args[i+1]
			i++
		} else if args[i] == "--dry-run" {
			flags[args[i]] = ""
		} else {
			name = config.SessionName(args[i])
		}
	}
	_, dryRun := flags["--dry-run"]
	if !dryRun && (!seatless() || reaped()) {
		return notImplemented(errOut, "orch")
	}
	if name != "" {
		if seat, known := seatNamed(name); seat != nil && dryRun {
			fmt.Fprintf(out, "orch: attaching to %s in %s (%s old)\n", name, seat.Path, run.Span(float64(time.Now().Unix()-seat.Created)))
			return 0
		} else if seat != nil || !known {
			return notImplemented(errOut, "orch")
		}
	}
	if !dryRun {
		current := ""
		if terminal.Typed() {
			var err error
			if current, _, err = config.CurrentSession(); err != nil {
				return refuse(errOut, err.Error())
			} else if current == "" {
				return notImplemented(errOut, "orch")
			}
		}
		seat, how := "no seat name given", "a new seat opens only from a terminal (the menu's n, or `ak orch NAME` typed there)"
		if name != "" {
			seat = "no seat named " + name
		}
		if current != "" {
			how = "a seat opens no seat: only the owner does, with the menu's n"
		}
		return refuse(errOut, seat+"; "+how+"\n"+orchUsage)
	}
	return preview(name, flags, out, errOut)
}

// preview is a new seat's dry run: the selection its flags make and the command it would run,
// opening nothing and writing nothing a seat keeps.  Go leaves to Python a seat it would have
// to ask about, a project it would file under and a provider's accounts.
func preview(name string, flags map[string]string, out, errOut io.Writer) int {
	forced, chosen := flags["--model"]
	raw, listed := flags["--workers"]
	// Python reads a lone flag before it asks for the rest, and a pair once it has the name
	if name == "" && chosen && listed {
		return notImplemented(errOut, "orch")
	}
	model, err := config.ModelNamed(forced)
	if chosen && err != nil {
		return refuse(errOut, err.Error())
	}
	var workers []string
	if listed {
		for _, worker := range strings.Split(raw, ",") {
			workers = append(workers, strings.TrimFunc(worker, config.Space))
		}
		if slices.Contains(workers, "") {
			return refuse(errOut, "--workers needs a comma-separated list of model names")
		}
		for _, worker := range workers {
			if _, err := config.ModelNamed(worker); err != nil {
				return refuse(errOut, err.Error())
			}
		}
		if len(slices.Compact(slices.Sorted(slices.Values(workers)))) != len(workers) {
			return refuse(errOut, "--workers contains duplicate model names")
		}
	}
	cwd := config.Resolve(".")
	if !listed || !chosen || mayBeProject(cwd) || len(model.Accounts) > 0 {
		return notImplemented(errOut, "orch")
	}
	rulebooks, err := os.MkdirTemp("", "ak-dry-run-")
	if err != nil {
		return refuse(errOut, err.Error())
	}
	defer os.RemoveAll(rulebooks)
	cmd, _, err := harness.Seat(forced, model, "", map[string]string{"AGENTKIT_SESSION": name, "AGENTKIT_SEAT_REPO": "", "AGENTKIT_RULEBOOK_DIR": rulebooks})
	if err != nil {
		return refuse(errOut, err.Error())
	}
	line := harness.Join(cmd)
	if term := tmux.Term(); term != "" {
		line = "TERM=" + term + " " + line
	}
	fmt.Fprintf(out, "orch: %s (--model)\nsession %s in %s (new)\nworkers %s\n%s\n", forced, name, cwd, strings.Join(workers, " "), line)
	return 0
}

// seatNamed is the live seat by that name, and whether Go knows: a seat whose harness exited,
// a record or rename pointer by that name and a session ak did not mark it leaves to Python,
// which resumes, follows or looks into them.
func seatNamed(name string) (*tmux.Session, bool) {
	path, _ := config.SessionPath(name)
	_, err := os.Lstat(path)
	recorded := err == nil
	for _, server := range []string{tmux.Own(), tmux.Default} {
		for _, session := range tmux.Sessions(server) {
			if config.Fold(session.Name) != name || server == tmux.Default && session.Mark != "1" {
				continue
			}
			if session.Mark != "1" && !recorded || tmux.Dead(server)[session.Name] {
				return nil, false
			}
			return &session, true
		}
	}
	return nil, !recorded
}

// reaped is whether the reap on Python's way in would act on a run, or might.
func reaped() bool {
	every, _ := records("", "")
	return every == nil || slices.ContainsFunc(every, actedOn)
}

// mayBeProject is whether a seat opened in cwd may be filed under a project: a checkout holds
// it, or a folder in ~/code.
func mayBeProject(cwd string) bool {
	code := config.Resolve(config.Expand("~/code"))
	for dir := cwd; ; dir = filepath.Dir(dir) {
		if _, err := os.Lstat(filepath.Join(dir, ".git")); err == nil || filepath.Dir(dir) == code {
			return true
		}
		if dir == filepath.Dir(dir) {
			return false
		}
	}
}

func refuse(errOut io.Writer, problem string) int {
	fmt.Fprintf(errOut, "ak orch: %s\n", problem)
	return 2
}

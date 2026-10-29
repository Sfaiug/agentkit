package cli

import (
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/project"
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
	if _, _, problem := parseOrch(args); problem != "" {
		return problem
	}
	if err := config.Check(); err != nil {
		return err.Error()
	}
	return ""
}

// parseOrch reads `ak orch [name] [--model NAME] [--workers A,B] [--dry-run]`, the name and
// flags in either order, as Python's parse does: the name a seat would be opened under, and
// each flag given, with its value.
func parseOrch(args []string) (string, map[string]string, string) {
	name, named, flags := "", false, map[string]string{}
	for i := 0; i < len(args); i++ {
		switch arg := args[i]; {
		case arg == "--dry-run":
			flags[arg] = ""
		case arg == "--model" && i+1 == len(args):
			return "", nil, "--model needs a model name"
		case arg == "--workers" && i+1 == len(args):
			return "", nil, "--workers needs a comma-separated list of model names"
		case arg == "--model" || arg == "--workers":
			flags[arg] = args[i+1]
			i++
		case strings.HasPrefix(arg, "-") || named:
			return "", nil, fmt.Sprintf("%s  (got %s)", orchUsage, commandhelp.Quote(arg))
		default:
			name, named = config.SessionName(arg), true
		}
	}
	return name, flags, ""
}

func init() { commands["orch"] = orch }

// orch is `ak orch [name]`, in Python's order: its arguments, then (outside a dry run) what it
// does on the way in, a seat by that name, the terminal and the models.  Go refuses an open
// nobody typed, or models a person's open names wrongly, and previews a new seat; it leaves to
// Python a way in that would act, a record its harness may rewrite, an attach, a resume, an
// open, a question and models it would pick by their usage.
func orch(args []string, out, errOut io.Writer) int {
	name, flags, _ := parseOrch(args)
	_, dryRun := flags["--dry-run"]
	if !dryRun && wayInActs() {
		return notImplemented(errOut, "orch")
	}
	held := false
	if name != "" {
		seat, panes, stranger := seatNamed(name)
		if seat != nil && dryRun && !tmux.Exited(panes, seat.Name) {
			fmt.Fprintf(out, "orch: attaching to %s in %s (%s old)\n", name, seat.Path, run.Span(float64(time.Now().Unix()-seat.Created)))
			return 0
		}
		// past a live seat, Python's records() has each harness reconcile every record
		if seat != nil || len(seatRecords()) > 0 {
			return notImplemented(errOut, "orch")
		}
		held = stranger
	}
	if !dryRun {
		current, typed := "", terminal.Typed()
		if typed {
			var err error
			if current, _, err = config.CurrentSession(); err != nil {
				return refuse(errOut, err.Error())
			}
		}
		if current != "" || !typed {
			seat, how := "no seat name given", "a new seat opens only from a terminal (the menu's n, or `ak orch NAME` typed there)"
			if name != "" {
				seat = "no seat named " + name
			}
			if current != "" {
				how = "a seat opens no seat: only the owner does, with the menu's n"
			}
			return refuse(errOut, seat+"; "+how+"\n"+orchUsage)
		}
	}
	forced, chosen := flags["--model"]
	raw, listed := flags["--workers"]
	// Python reads a lone flag before it asks for the name, and a pair once it has it
	if chosen != listed {
		if problem := selectionProblem(forced, chosen, raw, listed); problem != "" {
			return refuse(errOut, problem)
		}
	}
	if name == "" {
		return notImplemented(errOut, "orch")
	}
	if path, _ := config.SessionPath(name); exists(path) {
		// a rename pointer by that name, which Python follows to see whether it leads anywhere
		return notImplemented(errOut, "orch")
	}
	if held {
		return refuse(errOut, fmt.Sprintf("tmux already holds a session named %s, and it is no seat; pick another name", commandhelp.Quote(name)))
	}
	if problem := selectionProblem(forced, chosen, raw, listed); problem != "" {
		return refuse(errOut, problem)
	}
	model, _ := config.ModelNamed(forced)
	if !dryRun || !chosen || !listed || len(model.Accounts) > 0 {
		return notImplemented(errOut, "orch")
	}
	return preview(name, forced, model, workerNames(raw), out, errOut)
}

// selectionProblem is what is wrong with the models the flags given name, as Python's select
// reads them: the orchestrator's, then the workers'.
func selectionProblem(forced string, chosen bool, raw string, listed bool) string {
	if _, err := config.ModelNamed(forced); chosen && err != nil {
		return err.Error()
	}
	if !listed {
		return ""
	}
	workers := workerNames(raw)
	if slices.Contains(workers, "") {
		return "--workers needs a comma-separated list of model names"
	}
	for _, worker := range workers {
		if _, err := config.ModelNamed(worker); err != nil {
			return err.Error()
		}
	}
	if len(slices.Compact(slices.Sorted(slices.Values(workers)))) != len(workers) {
		return "--workers contains duplicate model names"
	}
	return ""
}

func workerNames(raw string) []string {
	var workers []string
	for _, worker := range strings.Split(raw, ",") {
		workers = append(workers, strings.TrimFunc(worker, config.Space))
	}
	return workers
}

// preview is a new seat's dry run: its selection, where it opens and the command it would run,
// opening nothing and writing nothing a seat keeps.
func preview(name, forced string, model config.Model, workers []string, out, errOut io.Writer) int {
	cwd := config.Resolve(".")
	repo := project.Of(cwd)
	opens := cwd
	if repo != "" {
		opens = repo
	}
	rulebooks, err := os.MkdirTemp("", "ak-dry-run-")
	if err != nil {
		return refuse(errOut, err.Error())
	}
	defer os.RemoveAll(rulebooks)
	cmd, _, err := harness.Seat(forced, model, "", map[string]string{"AGENTKIT_SESSION": name, "AGENTKIT_SEAT_REPO": repo, "AGENTKIT_RULEBOOK_DIR": rulebooks})
	if err != nil {
		return refuse(errOut, err.Error())
	}
	line := harness.Join(cmd)
	if term := tmux.Term(); term != "" {
		line = "TERM=" + term + " " + line
	}
	fmt.Fprintf(out, "orch: %s (--model)\nsession %s in %s (new)\nworkers %s\n%s\n", forced, name, opens, strings.Join(workers, " "), line)
	return 0
}

// seatNamed is the seat by that name, as Python's find reads it, with its server's panes, and
// whether a session ak's own server holds by that name is no seat.  On ak's server a session is
// a seat when ak marked it, a record names it or an agent runs in it; on the person's own, only
// one ak marked is.
func seatNamed(name string) (*tmux.Session, []tmux.Pane, bool) {
	recorded := seatRecords()
	stranger := false
	for _, server := range []string{tmux.Own(), tmux.Default} {
		panes, _ := tmux.Panes(server)
		for _, session := range tmux.Sessions(server) {
			if config.Fold(session.Name) != name || server == tmux.Default && session.Mark != "1" {
				continue
			}
			if session.Mark == "1" || recorded[session.Name] || !agentless(server, session.Name) {
				return &session, panes, false
			}
			stranger = true
		}
	}
	return nil, nil, stranger
}

// agentless is whether no interactive harness runs under a live pane of that session: an ak
// worker and what runs under it belong to a run.  What tmux or ps cannot answer says nothing.
func agentless(server, session string) bool {
	panes, answered := tmux.Panes(server)
	table := host.Processes()
	if !answered || table == nil {
		return false
	}
	patterns := config.AgentPrograms()
	children := map[int][]int{}
	for pid, process := range table {
		children[process.Parent] = append(children[process.Parent], pid)
	}
	var stack []int
	for _, pane := range panes {
		if _, known := table[pane.PID]; pane.Session == session && !pane.Dead && known {
			stack = append(stack, pane.PID)
		}
	}
	for seen := map[int]bool{}; len(stack) > 0; {
		pid := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if seen[pid] {
			continue
		}
		seen[pid] = true
		running := host.Program(table[pid].Words)
		if slices.ContainsFunc(patterns, func(pattern string) bool { matched, _ := path.Match(pattern, running); return matched }) {
			if !host.Worker(pid) {
				return false
			}
			continue // its descendants cannot make a seat either
		}
		stack = append(stack, children[pid]...)
	}
	return true
}

// seatRecords are the seats with a record, rename pointers aside; one Go cannot read counts.
func seatRecords() map[string]bool {
	records := map[string]bool{}
	for _, file := range config.SeatFiles() {
		record, err := run.ReadJSON(file)
		if err != nil || record == nil || record.Get(config.Renamed) == nil {
			records[strings.TrimSuffix(strings.TrimPrefix(filepath.Base(file), "session-"), ".json")] = true
		}
	}
	return records
}

// wayInActs is whether what Python does on its way in, outside a dry run (`orch.maintenance`),
// would act on a run or a seat, or might: reap a run, have a seat's harness reconcile its
// record, note when a seat was seen or retire it, or close a session whose panes all ended.
func wayInActs() bool {
	every, _ := records("", "")
	if every == nil || slices.ContainsFunc(every, actedOn) || len(seatRecords()) > 0 {
		return true
	}
	panes, _ := tmux.Panes(tmux.Own())
	for _, session := range tmux.Sessions(tmux.Own()) {
		if session.Mark != "1" && tmux.Exited(panes, session.Name) {
			return true
		}
	}
	return false
}

func refuse(errOut io.Writer, problem string) int {
	fmt.Fprintf(errOut, "ak orch: %s\n", problem)
	return 2
}

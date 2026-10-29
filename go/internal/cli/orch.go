package cli

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
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
// open, a name it would ask for, and an orchestrator or account it would pick by usage.
func orch(args []string, out, errOut io.Writer) int {
	name, flags, _ := parseOrch(args)
	_, dryRun := flags["--dry-run"]
	if !dryRun && wayInActs() {
		return notImplemented(errOut, "orch")
	}
	forced, given := flags["--model"]
	raw, listed := flags["--workers"]
	held, seats := false, map[string]*run.Object{}
	if name != "" {
		seat, panes, stranger := seatNamed(name)
		if seat != nil && dryRun && !tmux.Exited(panes, seat.Name) {
			fmt.Fprintf(out, "orch: attaching to %s in %s (%s old)\n", name, seat.Path, run.Span(float64(time.Now().Unix()-seat.Created)))
			return 0
		}
		// past a live seat, Python's records() has each harness reconcile every record, and a
		// seat whose session or record is left opens again as it was, unless a model or worker
		// named asks for a new one
		var readable bool
		seats, readable = seatRecords()
		_, recorded := seats[name]
		if seat != nil || !readable || rewritten(seats) || recorded && forced == "" && raw == "" {
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
	// Python reads a lone flag before it asks for the name, and a pair once it has it
	if given != listed {
		if problem := selectionProblem(forced, raw, listed); problem != "" {
			return refuse(errOut, problem)
		}
	}
	if name == "" {
		return notImplemented(errOut, "orch")
	}
	if _, recorded := seats[name]; !recorded && exists(sessionFile(name)) {
		// a rename pointer by that name, which Python follows to see whether it leads anywhere
		return notImplemented(errOut, "orch")
	}
	if held {
		return refuse(errOut, fmt.Sprintf("tmux already holds a session named %s, and it is no seat; pick another name", commandhelp.Quote(name)))
	}
	if forced == "" { // an empty --model names none: Python picks by usage
		return notImplemented(errOut, "orch")
	}
	if problem := selectionProblem(forced, raw, listed); problem != "" {
		return refuse(errOut, problem)
	}
	model, _ := config.ModelNamed(forced)
	if !dryRun || len(model.Accounts) > 0 {
		return notImplemented(errOut, "orch")
	}
	workers := workerNames(raw)
	if !listed {
		var back bool
		if workers, back = askWorkers(out); back {
			return 0
		}
	}
	return preview(name, forced, model, workers, out, errOut)
}

// selectionProblem is what is wrong with the models the flags name, as Python's select reads
// them: the orchestrator's, then the workers'.
func selectionProblem(forced, raw string, listed bool) string {
	if _, err := config.ModelNamed(forced); forced != "" && err != nil {
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

// askWorkers is Python's Workers question (`orch.prompt_workers`): names or numbers separated
// by spaces or commas, or all; Enter and the end of input take [defaults]' workers, and Esc
// goes back (true).
func askWorkers(out io.Writer) ([]string, bool) {
	names, defaults, _ := config.Offered()
	fmt.Fprintln(out)
	picked, back := ask(out, "Workers", strings.Join(defaults, " "), names, func(raw string) []string {
		if strings.ToLower(raw) == "all" {
			return slices.Clone(names)
		}
		var selected []string
		for _, part := range strings.FieldsFunc(raw, func(r rune) bool { return r == ',' || config.Space(r) }) {
			name, matches := "", choicesNamed(names, part)
			if number, err := strconv.Atoi(part); err == nil && digits(part) && 1 <= number && number <= len(names) {
				name = names[number-1]
			} else if len(matches) == 1 {
				name = matches[0]
			}
			if name == "" || slices.Contains(selected, name) {
				return nil
			}
			selected = append(selected, name)
		}
		return selected
	})
	if !back && picked == nil {
		picked = defaults
	}
	return picked, back
}

// ask is one new-seat question as Python's terminal.ask puts it: its choices dim above it,
// numbered and joined by ` · ` where the screen is narrow, then the question with its default
// in brackets.  The answer is a number or a name, or what allow makes of it; nothing typed is
// nil, Esc is back (true), and anything else is a dim `not a choice` and the question again.
func ask(out io.Writer, question, fallback string, choices []string, allow func(string) []string) ([]string, bool) {
	screen := terminal.For(out)
	room := screen.Width()
	var joined []string
	line := ""
	for i, choice := range choices {
		item := fmt.Sprintf("%d %s", i+1, choice)
		if terminal.Cells(item)+2 > room { // one choice wider than the screen is wrapped
			if line != "" {
				joined, line = append(joined, line), ""
			}
			joined = append(joined, terminal.Wrap(item, room-2)...)
			continue
		}
		added := item
		if line != "" {
			added = line + " · " + item
		}
		if line != "" && terminal.Cells(added)+2 > room {
			joined, line = append(joined, line), item
		} else {
			line = added
		}
	}
	if line != "" {
		joined = append(joined, line)
	}
	shown := promptLines(question+" ["+fallback+"]: ", room)
	in := bufio.NewReader(os.Stdin)
	for {
		for _, line := range joined {
			fmt.Fprintln(out, "  "+screen.Styled(line, "dim"))
		}
		for _, line := range shown[:len(shown)-1] {
			fmt.Fprintln(out, line)
		}
		fmt.Fprint(out, shown[len(shown)-1])
		typed, _ := in.ReadString('\n')
		if !terminal.Shows(out) {
			fmt.Fprintln(out)
		}
		answer := strings.TrimFunc(typed, config.Space)
		number, err := strconv.Atoi(answer)
		matches := choicesNamed(choices, answer)
		switch {
		case answer == "\x1b":
			return nil, true
		case answer == "":
			return nil, false
		case strings.HasPrefix(answer, "\x1b"): // a key's sequence: asked again, with no word
			continue
		case err == nil && digits(answer) && 1 <= number && number <= len(choices):
			return []string{choices[number-1]}, false
		case slices.Contains(choices, answer):
			return []string{answer}, false
		case len(matches) == 1:
			return matches, false
		}
		if accepted := allow(answer); accepted != nil {
			return accepted, false
		}
		fmt.Fprintln(out, screen.Styled("not a choice: "+commandhelp.Quote(answer), "dim"))
	}
}

// promptLines is a prompt wrapped on spaces to fit the screen, its cursor's space kept.
func promptLines(prompt string, room int) []string {
	room = max(1, room)
	if terminal.Cells(prompt) <= room {
		return []string{prompt}
	}
	body, pad := strings.CutSuffix(prompt, " ")
	lines := terminal.Wrap(body, room)
	if len(lines) == 0 {
		lines = []string{body}
	}
	if pad && terminal.Cells(lines[len(lines)-1])+1 <= room {
		lines[len(lines)-1] += " "
	} else if pad {
		lines = append(lines, " ")
	}
	return lines
}

func choicesNamed(choices []string, answer string) []string {
	var found []string
	for _, choice := range choices {
		if strings.ToLower(choice) == strings.ToLower(answer) {
			found = append(found, choice)
		}
	}
	return found
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
	seats, _ := seatRecords()
	stranger := false
	for _, server := range []string{tmux.Own(), tmux.Default} {
		panes, _ := tmux.Panes(server)
		for _, session := range tmux.Sessions(server) {
			if config.Fold(session.Name) != name || server == tmux.Default && session.Mark != "1" {
				continue
			}
			if _, recorded := seats[session.Name]; session.Mark == "1" || recorded || !agentless(server, session.Name) {
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
		if slices.ContainsFunc(patterns, func(pattern string) bool { return host.Match(pattern, running) }) {
			if !host.Worker(pid) {
				return false
			}
			continue // its descendants cannot make a seat either
		}
		stack = append(stack, children[pid]...)
	}
	return true
}

// seatRecords are the seats' records, rename pointers aside, as Python's session_records reads
// them, and whether Go read every one Python does.
func seatRecords() (map[string]*run.Object, bool) {
	seats, readable := map[string]*run.Object{}, true
	for _, file := range config.SeatFiles() {
		record, err := run.ReadJSON(file)
		readable = readable && !errors.Is(err, run.ErrLoneSurrogate)
		if record != nil && !record.Has(config.Renamed) {
			seats[strings.TrimSuffix(strings.TrimPrefix(filepath.Base(file), "session-"), ".json")] = record
		}
	}
	return seats, readable
}

func sessionFile(name string) string {
	path, _ := config.SessionPath(name)
	return path
}

// rewritten is whether Python's records() would rewrite one of the records, or may: each
// through its seat's harness.
func rewritten(seats map[string]*run.Object) bool {
	for _, record := range seats {
		model, _ := config.ModelNamed(record.Str("orchestrator"))
		if harness.Rewrites(model.Harness, record) {
			return true
		}
	}
	return false
}

// seenEvery is how often Python stamps a live seat's record with the time it was seen.
const seenEvery = 300

// wayInActs is whether what Python does on its way in, outside a dry run (`orch.maintenance`),
// would act on a run or a seat, or might: reap a run (`reconcile`), rewrite a seat's record,
// note when a seat was seen or ended (`stamp`), retire one gone or ended for a week, or close a
// session that is no seat once all its panes ended a day ago (`sweep`).
func wayInActs() bool {
	every, _ := records("", "")
	seats, readable := seatRecords()
	if every == nil || !readable || slices.ContainsFunc(every, actedOn) || rewritten(seats) {
		return true
	}
	now := float64(time.Now().UnixNano()) / 1e9
	type held struct{ exited, attached bool }
	sessions := map[string]held{}
	for _, server := range []string{tmux.Own(), tmux.Default} {
		panes, _ := tmux.Panes(server)
		for _, session := range tmux.Sessions(server) {
			_, recorded := seats[session.Name]
			if server == tmux.Own() && session.Mark != "1" && !recorded && endedBefore(panes, session.Name, now-86400) {
				return true
			}
			if _, found := sessions[session.Name]; !found && (server == tmux.Own() || session.Mark == "1") {
				sessions[session.Name] = held{tmux.Exited(panes, session.Name), session.Attached}
			}
		}
	}
	for name, record := range seats {
		session, seat := sessions[name]
		seen, stamped := run.Num(record.Get("seen"))
		switch since := record.Get("exited_since"); {
		case seat && session.exited && !session.attached:
			if !record.Truthy("exited_since") || expired(since, now) {
				return true
			}
		case seat:
			if record.Truthy("exited_since") || !stamped || now-seen > seenEvery {
				return true
			}
		default:
			if since = stoppedAt(name); since == nil {
				since = record.Get("seen")
			}
			if !record.Truthy("seen") || expired(since, now) {
				return true
			}
		}
	}
	return false
}

// endedBefore is whether every pane of the session ended, the last before that moment.
func endedBefore(panes []tmux.Pane, session string, moment float64) bool {
	ended := false
	for _, pane := range panes {
		if pane.Session == session {
			if !pane.Dead || pane.Died <= 0 || float64(pane.Died) > moment {
				return false
			}
			ended = true
		}
	}
	return ended
}

// expired is Python's retention.expired for a seat record: a finite moment a week or more ago.
func expired(value any, now float64) bool {
	moment, numeric := run.Num(value)
	return numeric && !math.IsInf(moment, 0) && !math.IsNaN(moment) && 0 < moment && moment <= now-7*86400
}

// stoppedAt is when the owner stopped that seat, as its state file says, nil for never.
func stoppedAt(name string) any {
	state, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "seat-"+name+".json"))
	if state == nil || !state.Truthy("stopped_at") {
		return nil
	}
	return state.Get("stopped_at")
}

func refuse(errOut io.Writer, problem string) int {
	fmt.Fprintf(errOut, "ak orch: %s\n", problem)
	return 2
}

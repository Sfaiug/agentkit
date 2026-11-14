package cli

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/launch"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func init() { commands["run status"] = runStatus }

var statusHeaders = []string{"id", "title", "state", "worker", "round", "age"}

// A listed run is its directory and its record, or the unreadable row in its place, and its place
// in its landing line, "" out of any; a job's task alone is one read for the job's block, no row.
type listed struct {
	dir          string
	record       *run.Object
	unreadable   bool
	ending       string
	recordEnding func()
	place        string
	task         bool
}

func (l listed) name() string { return filepath.Base(l.dir) }

// runStatus is `ak run status`: the host lines, then the runs of the last seven days, or
// every run and the scoreboard with --history, or the one run an id names, whose ending the
// look marks looked at, and whose waiting ending its own seat reads as handed back; or, with
// --tests alone, the test audit.
func runStatus(args []string, out, errOut io.Writer) int {
	if contains(args, "--tests") {
		return testAudit(out, errOut)
	}
	showHistory, machine := contains(args, "--history"), contains(args, "--json")
	plain, why, pending := contains(args, "--plain"), contains(args, "--why"), contains(args, "--pending")
	wanted := strings.Join(without(args, "--history", "--json", "--plain", "--why", "--pending"), "")
	if wanted != "" && jobNamed(wanted) {
		// a look at a job reaps the job
		return notImplemented(errOut, "run status")
	}
	now := time.Now()
	caller, _, err := config.CurrentSession()
	seat := caller
	if wanted != "" {
		// any run still shows by its id
		seat = ""
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak run: %s\n", err)
		return 2
	}
	var db *history.DB
	defer func() { db.Close() }()
	// read before anything is written: history.db Go cannot read as Python's machine form does
	// leaves it the command
	if machine {
		if db, err = history.Reader(); err != nil {
			return notImplemented(errOut, "run status")
		}
	}
	looked := false
	if wanted != "" {
		if _, _, _, no := listing(seat, wanted, showHistory, machine, now); no {
			return notImplemented(errOut, "run status")
		}
		if !machine && lookLeft(caller, filepath.Join(run.Runs(), wanted)) {
			return notImplemented(errOut, "run status")
		}
		// a mark that cannot be written is let go, as Python lets it go: what is shown
		// never depends on it
		err := run.Change(filepath.Join(run.Runs(), wanted), func(record *run.Object) (err error) {
			looked, err = look(record)
			return err
		})
		if errors.Is(err, errLeft) || errors.Is(err, run.ErrLoneSurrogate) {
			return notImplemented(errOut, "run status")
		}
		looked = looked && err == nil
	}
	lines := ""
	if !machine {
		if lines, err = host.StatusLines(); err != nil {
			fmt.Fprintf(errOut, "ak run: %s\n", err)
			return 2
		}
	}
	every, entries, jobs, no := listing(seat, wanted, showHistory, machine, now)
	var uncounted []string
	// opened before a line is printed: a database Go leaves to Python ak leaves it the command;
	// decided on while the reap holds its runs, so neither is written where the other refuses
	if no || !reaped(entries, func() (err error) {
		if showHistory && wanted == "" && !machine {
			db, uncounted, err = boardHistory()
		}
		return err
	}) {
		return notImplemented(errOut, "run status")
	}
	for i := range entries {
		if looked && !machine && !entries[i].unreadable {
			// the look that just marked an ending still shows it as it found it
			entries[i].record = entries[i].record.Copy()
			entries[i].record.Set("recovery_acknowledged_at", nil)
		}
	}
	screen := terminal.For(out)
	viewer := out
	var viewed strings.Builder
	if wanted != "" && !machine {
		out = &viewed
	}
	if !machine {
		fmt.Fprintln(out, lines)
		if seat != "" {
			// an empty answer here is this seat's, never the host's
			fmt.Fprintf(out, "seat %s's runs only; ak orch list shows every seat's\n", seat)
		}
	}
	var found []listed
	hidden := 0
	for _, entry := range entries {
		if entry.task {
			continue
		}
		if wanted == "" && !shown(entry.record, showHistory, now) {
			hidden++
			continue
		}
		found = append(found, entry)
	}
	if pending {
		found = slices.DeleteFunc(found, func(entry listed) bool { return run.HandbackWaiting(entry.record) == "" })
	}
	sort.SliceStable(found, func(i, j int) bool { return later(found[i].record, found[j].record, now) })
	if machine {
		rows := []any{}
		for _, entry := range found {
			rows = append(rows, machineRow(db, entry))
		}
		fmt.Fprintln(out, run.Encode(rows))
		return 0
	}
	endingLines(found, caller, wanted)
	var others []*run.Object
	for _, entry := range every {
		if !run.SmokeRun(entry) {
			others = append(others, entry)
		}
	}
	index, models := run.NewIndex(others), run.Models()
	printJobs(out, jobs, entries, models, index, now)
	if len(found) == 0 && len(jobs) == 0 {
		fmt.Fprintf(out, "no current runs in %s\n", run.Runs())
	}
	if plain {
		for _, entry := range found {
			printPlain(out, screen, entry, why, models, now)
		}
	} else if len(found) > 0 {
		header, groups := statusRows(screen, found, index, models, now)
		fmt.Fprintln(out, header)
		for i, entry := range found {
			fmt.Fprintln(out, strings.Join(groups[i], "\n"))
			lines := brief(screen, entry, index, now)
			if why || wanted != "" {
				lines = details(screen, entry, index, now)
			}
			for _, line := range lines {
				fmt.Fprintln(out, line)
			}
		}
	}
	if wanted != "" {
		if err := printedLook(viewer, viewed.String(), found); err != nil {
			fmt.Fprintf(errOut, "ak run: %s\n", err)
			return 1
		}
		return 0
	}
	fmt.Fprintf(out, "%d older run(s) hidden; ak run status --history [--json] shows full history\n", hidden)
	if showHistory {
		fmt.Fprintln(out, strings.Join(append(scoreboard(screen, db, uncounted, now), sizeLines(db)...), "\n"))
	}
	return 0
}

// listing is every readable record, the runs a listing reads and the jobs it shows, none with
// --json or for one run named, each line's places read once where the listing prints them, or
// none, and true, where Go leaves the listing to Python (`refused`, a receipt Go cannot keep, or
// a place not landing.line's).
func listing(seat, wanted string, showHistory, machine bool, now time.Time) ([]*run.Object, []listed, []job.Shown, bool) {
	var jobs []job.Shown
	read := true
	if wanted == "" && !machine {
		jobs, read = job.Listed(seat, showHistory, now)
	}
	every, entries := records(seat, wanted, tasks(jobs))
	if !read || every == nil || refused(entries, wanted) {
		return nil, nil, nil, true
	}
	if !machine {
		place := run.LinePlaces(run.Standing())
		for i := range entries {
			var read bool
			if entries[i].place, read = place(entries[i].record, entries[i].name()); !read {
				return nil, nil, nil, true
			}
		}
	}
	return every, entries, jobs, false
}

// reaped is whether each run listed is now as Python's reap leaves it: an ended one as run.Reap
// leaves it, the ones handback reaps reaped together, decide made before they are swept.  False
// where one moved on to a reap Go leaves to Python, decide refused, or a stamp went unwritten.
func reaped(entries []listed, decide func() error) bool {
	var swept []*listed
	var dirs []string
	for i := range entries {
		switch entry := &entries[i]; {
		case entry.unreadable:
		case handback.Reapable(entry.record):
			swept, dirs = append(swept, entry), append(dirs, entry.dir)
		default:
			entry.record, _ = run.Reap(entry.record)
		}
	}
	records, err := handback.Reap(dirs, decide)
	for i, record := range records {
		swept[i].record = record
	}
	return err == nil
}

// records are every readable record, and the runs a listing reads: the one wanted, smoke run
// or not, or every run, or the seat's own, the smoke suite's aside, an unreadable record as a
// row saying so outside a seat, and any other run a job's task names.  None at all where a
// record holds what Go cannot keep.
func records(seat, wanted string, tasks map[string]bool) ([]*run.Object, []listed) {
	every := []*run.Object{}
	var kept []listed
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, nil
		}
		if record != nil {
			every = append(every, record)
		}
		switch {
		case wanted != "" && filepath.Base(dir) != wanted:
		case seat != "" && (record == nil || run.Seat(record) != seat), record != nil && wanted == "" && run.SmokeRun(record):
			if record != nil && tasks[filepath.Base(dir)] {
				kept = append(kept, listed{dir: dir, record: record, task: true})
			}
		case record == nil:
			record = run.NewObject()
			record.Set("run_id", filepath.Base(dir))
			record.Set("state", "unreadable")
			kept = append(kept, listed{dir: dir, record: record, unreadable: true})
		default:
			kept = append(kept, listed{dir: dir, record: record})
		}
	}
	return every, kept
}

var errLeft = errors.New("left to Python ak")

// look marks the run's ending looked at, and is whether it marked, or errLeft where Python ak
// would do more for the look than Go does: act on the run as its reap does, or count a place
// in a landing line as its write does.
func look(record *run.Object) (bool, error) {
	if actedOn(record) {
		return false, errLeft
	}
	marked := run.LookedAt(record, time.Now())
	if marked && run.Lined(record) {
		return false, errLeft
	}
	return marked, nil
}

// actedOn is whether Python's reap would act on the run as Go does not: end processes it left
// behind, reap an active run whose loop is gone, offer a wait's recovery, or reap one neither
// active, waiting, stalled, ended nor untold, past what handback.Reap does.
func actedOn(record *run.Object) bool {
	_, owed := run.Reap(record)
	switch state := record.Str("state"); {
	case owed:
		return true
	case run.Active(record):
		// a launch waiting for its slot is the tick's to adopt
		return !run.GoesOn(record, seconds(time.Now())) && !(state == "queued" && record.Truthy("slot_waiting"))
	case state == "waiting":
		return run.NeedsRecovery(record)
	default:
		return state != "stalled" && !run.Ended(record) && !handback.Untold(record) && !handback.Reapable(record)
	}
}

// refused is whether Python ak would write or act on what the listing reads: a run its reap or
// a look at it acts on, a job's task's among them.  The scoreboard's own reads are boardHistory's,
// the machine form's history.Reader's.
func refused(entries []listed, wanted string) bool {
	for _, entry := range entries {
		if entry.unreadable {
			continue
		}
		if _, err := look(entry.record.Copy()); actedOn(entry.record) || wanted != "" && err != nil {
			return true
		}
		// a review of a pull request with review off is Python's whole, its status too
		if !run.Carries(entry.record) {
			return true
		}
		if entry.record.Str("state") == "queued" {
			if _, read := launch.SlotNote(entry.record); !read {
				return true
			}
		}
	}
	return false
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func seconds(at time.Time) float64 {
	return float64(at.UnixNano()) / 1e9
}

// shown is whether a listing shows the run: any with --history, else all but what ended
// over seven days ago and needs nothing more.  An admitted error or wait still belongs to the tick.
func shown(record *run.Object, showHistory bool, now time.Time) bool {
	state := record.Str("state")
	live := run.Going(record, now) && (state == "error" || state == "waiting")
	ended := run.FirstNumber(record, "finished_at", "started_at")
	return showHistory || contains([]string{"queued", "running", "stalled", "unreadable"}, state) ||
		run.Actionable(record, now) || live || seconds(now)-ended <= run.GCAge
}

// later orders runs as the listing does: the ones a loop holds, then those still owed
// something, newest first by their interruption, ending or start.
func later(a, b *run.Object, now time.Time) bool {
	if run.Active(a) != run.Active(b) {
		return run.Active(a)
	}
	if run.Actionable(a, now) != run.Actionable(b, now) {
		return run.Actionable(a, now)
	}
	return run.FirstNumber(a, "interrupted_at", "finished_at", "started_at") >
		run.FirstNumber(b, "interrupted_at", "finished_at", "started_at")
}

func resultPaths(entry listed) *run.Object {
	paths := run.NewObject()
	paths.Set("result", filepath.Join(entry.dir, "result.md"))
	paths.Set("record", filepath.Join(entry.dir, "run.json"))
	paths.Set("logs", entry.dir)
	paths.Set("workspace", entry.record.Get("worktree"))
	paths.Set("workspace_present", workspacePresent(entry.record))
	return paths
}

func workspacePresent(record *run.Object) bool {
	return record.Str("worktree") != "" && exists(record.Str("worktree"))
}

// statusIDCell is the id whole where it fits, else its date and time and the slug cut at a word.
func statusIDCell(name string, room int) string {
	if terminal.Cells(name) <= room {
		return name
	}
	if len(name) < 14 || !config.Digits(name[:8]) || name[8] != '-' || !config.Digits(name[9:13]) || name[13] != '-' {
		return terminal.Cut(name, room)
	}
	head, slug := name[:8]+" "+name[9:13]+" ", name[14:]
	if terminal.Cells(head) >= room {
		return terminal.Cut(name, room)
	}
	room -= terminal.Cells(head)
	if terminal.Cells(slug) <= room {
		return head + slug
	}
	// whole words only; the ellipsis takes the last cell
	current := ""
	for i, word := range strings.Split(slug, "-") {
		added := word
		if i > 0 {
			added = current + "-" + word
		}
		if terminal.Cells(added) > room-1 {
			break
		}
		current = added
	}
	if current == "" {
		return head + terminal.Cut(slug, room)
	}
	return head + current + "…"
}

// roundCell is `round 2/3`, or `no review`, with any extension.
func roundCell(record *run.Object) string {
	done := len(record.List("round_summaries"))
	total, _ := record.Num("rounds")
	shown := fmt.Sprint(done)
	if run.Active(record) && record.Truthy("rounds") {
		if total < float64(done+1) {
			shown = run.Text(record.Get("rounds"))
		} else {
			shown = fmt.Sprint(done + 1)
		}
	}
	if record.Truthy("own_pr_round_pending") {
		shown = run.Text(record.Get("own_pr_round_pending"))
	}
	of := "?"
	if record.Truthy("rounds") {
		of = run.Text(record.Get("rounds"))
	}
	cell := "round " + shown + "/" + of
	if run.ReviewOff(record) {
		cell = "no review"
	}
	if record.Truthy("extended") {
		cell += " (+" + run.Text(record.Get("extended")) + ")"
	}
	return cell
}

// statusRows is the table's header and each run's lines: id, title (all the room left,
// wrapped once), state, worker, round and age; under 12 cells of title, each run's id and
// title sit over its state line.
func statusRows(screen terminal.Screen, found []listed, index run.Index, models map[string]config.Model, now time.Time) (string, [][]string) {
	width := screen.ContentWidth()
	dims := []string{"dim", "dim", "dim", "dim", "dim", "dim"}
	var rows [][]string
	for _, entry := range found {
		record := entry.record
		worker := run.Field(record, "executor", "?") + "/" + run.Field(record, "reviewer", "?")
		if run.SelfReviewed(record, models) {
			worker += " self-reviewed"
		}
		title := entry.name()
		if record.Truthy("title") {
			title = run.Text(record.Get("title"))
		}
		age := run.ResumeAge(record, now)
		if age == "" {
			age = terminal.FormatAge(run.AgeSeconds(record, now))
		}
		rows = append(rows, []string{entry.name(), title, entry.stateWord(index, now), worker, roundCell(record), age})
	}
	natural := make([]int, 4)
	for n, column := range []int{2, 3, 4, 5} {
		natural[n] = terminal.Cells(statusHeaders[column])
		for _, row := range rows {
			natural[n] = max(natural[n], terminal.Cells(row[column]))
		}
	}
	stateTexts := make([]string, len(rows))
	natural[0] = terminal.Cells(statusHeaders[2])
	idWidest := 0
	for i, row := range rows {
		stateTexts[i] = screen.StateText(row[2])
		natural[0] = max(natural[0], terminal.Cells(stateTexts[i]))
		idWidest = max(idWidest, terminal.Cells(row[0]))
	}
	const gutter, titleMin = 2, 20
	fixed := natural[0] + natural[1] + natural[2] + natural[3]
	idRoom := min(idWidest, max(15, width-fixed-gutter*5-titleMin))
	titleRoom := width - idRoom - fixed - gutter*5
	narrow := titleRoom < 12
	firstRoom := max(1, width-idRoom-gutter)
	widths := []int{idRoom, max(1, titleRoom), natural[0], natural[1], natural[2], natural[3]}
	header := screen.TableRow(statusHeaders, widths, dims)
	if narrow {
		header = screen.TableRow(statusHeaders[:2], []int{idRoom, firstRoom}, dims)
	}
	indent := strings.Repeat(" ", idRoom+gutter)
	var groups [][]string
	for i, row := range rows {
		word, line := row[2], stateTexts[i]
		cell := statusIDCell(row[0], idRoom)
		var group []string
		if !narrow {
			titled := terminal.TitleLines(row[1], titleRoom)
			group = append(group, screen.TableRow([]string{cell, titled[0], line, row[3], row[4], row[5]},
				widths, []string{"", "", word}))
			if len(titled) > 1 {
				group = append(group, indent+titled[1])
			}
			groups = append(groups, group)
			continue
		}
		titled := terminal.TitleLines(row[1], firstRoom)
		group = append(group, screen.TableRow([]string{cell, titled[0]}, []int{idRoom, firstRoom}, nil))
		if len(titled) > 1 {
			group = append(group, indent+titled[1])
		}
		// the tail is measured plain and printed coloured: a cut never touches a styled
		// cell, and the state itself is never cut
		tail := []string{line, row[3], row[4], row[5]}
		if terminal.Cells("  "+strings.Join(tail, "  ")) <= width {
			tail[0] = screen.StateCell(word)
			group = append(group, strings.TrimRight("  "+strings.Join(tail, "  "), " "))
		} else {
			head, rest := tail[:2], tail[2:]
			if over := terminal.Cells("  "+strings.Join(head, "  ")) - width; over > 0 {
				head[1] = terminal.Cut(head[1], max(1, terminal.Cells(head[1])-over))
			}
			head[0] = screen.StateCell(word)
			group = append(group, strings.TrimRight("  "+strings.Join(head, "  "), " "),
				strings.TrimRight("  "+strings.Join(rest, "  "), " "))
		}
		groups = append(groups, group)
	}
	return header, groups
}

// brief is the notes under a row of the listing: one that says why it waits, then whether
// it goes first, what still runs under it and what ended it.
func brief(screen terminal.Screen, entry listed, index run.Index, now time.Time) []string {
	record := entry.record
	var lines []string
	dim := func(text string) string { return "  " + screen.Styled(text, "dim") }
	switch wait, note := waitNote(record), entry.parked(now); {
	case entry.ending != "":
		lines = append(lines, "  "+entry.ending)
	case wait != "":
		lines = append(lines, "  "+wait)
	case run.BlockedNote(record, "!") != "":
		lines = append(lines, dim(run.BlockedNote(record, screen.Glyph(run.Word(record, index, now)))))
	case run.HandbackWaiting(record) != "":
		lines = append(lines, dim(run.HandbackWaiting(record)))
	case note != "":
		lines = append(lines, dim(note))
	}
	return append(lines, tail(screen, record)...)
}

// parked is Python's status.parked_line: the run's place in its landing line, else its retry or
// who it waits for.
func (l listed) parked(now time.Time) string {
	return cmp.Or(l.place, run.ParkedLine(l.record, l.name(), now))
}

// waitNote is what a run waits for before it works on: a queued one its slot, a running one a
// heavy suite turn.
func waitNote(record *run.Object) string {
	if record.Str("state") == "queued" {
		note, _ := launch.SlotNote(record)
		return note
	}
	return run.GateTurnNote(record)
}

// tail is the notes every format ends a run's lines with: whether it goes first, what still
// runs under it and what ended it.
func tail(screen terminal.Screen, record *run.Object) []string {
	var lines []string
	if record.Truthy("first") {
		lines = append(lines, "  first")
	}
	for _, note := range []string{run.Alive(record), run.StopNote(record, screen.Glyph("FAIL"))} {
		if note != "" {
			lines = append(lines, "  "+screen.Styled(note, "dim"))
		}
	}
	return lines
}

func short(record *run.Object, key string, fallback int) string {
	if !record.Has(key) {
		return fmt.Sprint(fallback)
	}
	if value, ok := record.Num(key); ok {
		return host.Short(value)
	}
	return run.Text(record.Get(key))
}

func limits(record *run.Object) string {
	return "  limits: silence_minutes=" + short(record, "silence_minutes", run.SilenceMinutes) +
		", ceiling_hours=" + short(record, "ceiling_hours", run.CeilingHours)
}

// joined is `', '.join(value)` of a list of names, or of a string's characters.
func joined(value any) string {
	var parts []string
	switch value := value.(type) {
	case []any:
		for _, item := range value {
			parts = append(parts, run.Text(item))
		}
	case string:
		for _, r := range value {
			parts = append(parts, string(r))
		}
	default:
		return run.Text(value)
	}
	return strings.Join(parts, ", ")
}

func workspaceLine(record *run.Object) string {
	return "  workspace: " + run.Text(record.Get("worktree")) + " (" + run.WorkspaceLocation(record, workspacePresent(record)) + ")"
}

// details is the lines under one run's row: result, record, limits, workspace and final check,
// and where it waits, why it stopped and what reopens it.
func details(screen terminal.Screen, entry listed, index run.Index, now time.Time) []string {
	record, dir := entry.record, entry.dir
	dim := func(text string) string { return "  " + screen.Styled(text, "dim") }
	lines := []string{"  result: " + filepath.Join(dir, "result.md"), "  record: " + filepath.Join(dir, "run.json"), limits(record)}
	for _, role := range []string{"workers", "reviewers"} {
		if record.Get(role) != nil {
			lines = append(lines, "  "+role+": "+joined(record.Get(role)))
		}
	}
	if record.Truthy("worktree") {
		lines = append(lines, workspaceLine(record))
	}
	if checked := run.FinalCheck(dir, record); checked != "" {
		lines = append(lines, "  "+checked)
	}
	if record.Truthy("first") {
		lines = append(lines, "  first")
	}
	if stalled := run.StallSummary(record); stalled != "" {
		lines = append(lines, "  "+stalled)
	}
	lines = append(lines, run.DeathLines(record)...)
	if note := waitNote(record); note != "" {
		lines = append(lines, "  "+note)
	}
	if record.Truthy("slot_stall") {
		lines = append(lines, "  "+run.Text(record.Get("slot_stall")))
	}
	if run.NeedsRecovery(record) {
		lines = append(lines, "  "+run.RecoveryReason(record)+"; ak run resume "+entry.name()+" offers recovery")
	}
	for _, note := range []string{run.BlockedNote(record, screen.Glyph(run.Word(record, index, now))),
		entry.parked(now), run.HandbackWaiting(record), run.Alive(record), run.StopNote(record, screen.Glyph("FAIL"))} {
		if note != "" {
			lines = append(lines, dim(note))
		}
	}
	if onward := run.ContinueLine(record, dir, now); onward != "" {
		lines = append(lines, "  "+onward)
	}
	if entry.ending != "" {
		lines = append(lines, "  "+entry.ending)
	}
	return lines
}

// padded is text left-aligned in `width` characters, as Python's format pads.
func padded(text string, width int) string {
	return text + strings.Repeat(" ", max(0, width-utf8.RuneCountInString(text)))
}

// printPlain is `--plain`'s line format, one run a line and its paths under it.
func printPlain(out io.Writer, screen terminal.Screen, entry listed, why bool, models map[string]config.Model, now time.Time) {
	record, name := entry.record, entry.name()
	branch := "scratch"
	if record.Truthy("branch") {
		branch = run.Text(record.Get("branch"))
	}
	word := run.Field(record, "state", "?")
	if word == "queued" {
		word = "waiting"
	}
	line := padded(name, 40) + " " + padded(word, 11) + " " + padded(run.Text(record.Get("verdict")), 5) + " " +
		run.ExecutorLine(record) + "/" + run.Field(record, "reviewer", "?") + "  " + branch
	if run.ReviewOff(record) {
		line += "  no review"
	}
	outcome, step := run.Outcome(record, models), run.StepWord(record, now)
	if record.Truthy("extended") {
		line += fmt.Sprintf("  round %d/%s (+%s)", len(record.List("round_summaries")), run.Text(record.Get("rounds")), run.Text(record.Get("extended")))
	}
	if stalled := run.StallSummary(record); stalled != "" {
		line += "  " + stalled
	}
	if run.NeedsRecovery(record) {
		line += "  " + run.RecoveryReason(record) + "; ak run resume " + name + " offers recovery"
	}
	if record.Str("state") == "blocked" {
		line += "  blocked: " + strings.Join(strings.Fields(record.Str("error")), " ")
	}
	if record.Truthy("pr") {
		line += "  " + outcome + " " + run.Text(record.Get("pr"))
	} else if outcome != "" {
		line += "  " + outcome
	}
	if step != "" {
		line += "  " + step
	}
	if run.SelfReviewed(record, models) {
		line += "  self-reviewed"
	}
	if resumed := run.ResumeAge(record, now); resumed != "" {
		line += "  " + resumed
	}
	if waiting := run.HandbackWaiting(record); waiting != "" {
		line += "  " + screen.Styled(waiting, "dim")
	}
	lines := []string{line}
	if entry.ending != "" {
		lines = append(lines, "  "+entry.ending)
	}
	if note := cmp.Or(entry.place, waitNote(record)); note != "" {
		lines = append(lines, "  "+note)
	}
	lines = append(lines, tail(screen, record)...)
	if why {
		lines = append(lines, limits(record))
	}
	lines = append(lines, "  result: "+filepath.Join(entry.dir, "result.md")+"  record/logs: "+entry.dir)
	if record.Truthy("worktree") {
		lines = append(lines, workspaceLine(record))
	}
	if checked := run.FinalCheck(entry.dir, record); checked != "" {
		lines = append(lines, "  "+checked)
	}
	lines = append(lines, run.DeathLines(record)...)
	if onward := run.ContinueLine(record, entry.dir, now); onward != "" {
		lines = append(lines, "  "+onward)
	}
	fmt.Fprintln(out, strings.Join(lines, "\n"))
}

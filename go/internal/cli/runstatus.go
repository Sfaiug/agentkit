package cli

import (
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
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func init() { commands["run status"] = runStatus }

var statusHeaders = []string{"id", "title", "state", "worker", "round", "age"}

// A listed run is its directory and its record, or the unreadable row in its place.
type listed struct {
	dir        string
	record     *run.Object
	unreadable bool
}

func (l listed) name() string { return filepath.Base(l.dir) }

// runStatus is `ak run status`: the host lines, then the runs of the last seven days, or
// every run and the scoreboard with --history.  Go writes nothing in the home yet, so what
// Python ak would write or act on there, it refuses before it prints anything (`refused`).
func runStatus(args []string, out, errOut io.Writer) int {
	showHistory, machine := contains(args, "--history"), contains(args, "--json")
	plain, why, pending := contains(args, "--plain"), contains(args, "--why"), contains(args, "--pending")
	if len(without(args, "--history", "--json", "--plain", "--why", "--pending")) > 0 {
		// a look at one run marks its ending looked at, and one at a job reaps the job
		return notImplemented(errOut, "run status")
	}
	now := time.Now()
	seat, _, err := config.CurrentSession()
	if err != nil {
		fmt.Fprintf(errOut, "ak run: %s\n", err)
		return 2
	}
	every, kept := records(seat)
	lines := ""
	if !machine {
		if lines, err = host.StatusLines(); err != nil {
			fmt.Fprintf(errOut, "ak run: %s\n", err)
			return 2
		}
	}
	entries, owed := reaped(kept)
	if every == nil || owed || refused(entries, seat, showHistory, machine, now) {
		return notImplemented(errOut, "run status")
	}
	screen := terminal.For(out)
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
		if !shown(entry.record, showHistory, now) {
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
			row := entry.record.Copy()
			row.Set("paths", resultPaths(entry))
			rows = append(rows, row)
		}
		fmt.Fprintln(out, run.Encode(rows))
		return 0
	}
	var others []*run.Object
	for _, entry := range every {
		if !run.SmokeRun(entry) {
			others = append(others, entry)
		}
	}
	index, models := run.NewIndex(others), run.Models()
	if len(found) == 0 {
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
			if why {
				lines = details(screen, entry, index, now)
			}
			for _, line := range lines {
				fmt.Fprintln(out, line)
			}
		}
	}
	fmt.Fprintf(out, "%d older run(s) hidden; ak run status --history [--json] shows full history\n", hidden)
	if showHistory {
		fmt.Fprintln(out, strings.Join(scoreboard(screen, now), "\n"))
	}
	return 0
}

// records are every readable record, and the runs a listing reads: every run, or the seat's
// own, the smoke suite's aside, an unreadable record as a row saying so outside a seat.  None
// at all where a record holds what Go cannot keep.
func records(seat string) ([]*run.Object, []listed) {
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
		case seat != "" && (record == nil || run.Seat(record) != seat):
		case record == nil:
			record = run.NewObject()
			record.Set("run_id", filepath.Base(dir))
			record.Set("state", "unreadable")
			kept = append(kept, listed{dir, record, true})
		case !run.SmokeRun(record):
			kept = append(kept, listed{dir, record, false})
		}
	}
	return every, kept
}

// reaped is each run as Python's reap leaves it for the listing, and whether that reap would
// end processes a run left behind.
func reaped(entries []listed) ([]listed, bool) {
	for i, entry := range entries {
		if entry.unreadable {
			continue
		}
		record, owed := run.Reap(entry.record)
		if owed {
			return nil, true
		}
		entries[i].record = record
	}
	return entries, false
}

// refused is whether Python ak would write or act on what the listing reads: a job it shows,
// a run in a state whose reap Go leaves to Python (one neither running, stalled nor ended, a
// running one whose loop is gone, a place in a landing line), and with --json or --history
// what history.db and the seats would add.
func refused(entries []listed, seat string, showHistory, machine bool, now time.Time) bool {
	if exists(filepath.Join(config.Home(), "history.db")) && (machine || showHistory) {
		return true
	}
	if showHistory && config.SeatRecorded() {
		return true
	}
	if jobShown(seat, showHistory, machine, now) {
		return true
	}
	for _, entry := range entries {
		record := entry.record
		switch state := record.Str("state"); {
		case entry.unreadable:
		case state != "running" && state != "stalled" && !run.Ended(record),
			state == "running" && !run.ProcessActive(record), run.InLine(record):
			return true
		}
	}
	return false
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// jobShown is whether the listing shows a job: the seat's or every one of the last seven
// days, all of them with --history.
func jobShown(seat string, showHistory, machine bool, now time.Time) bool {
	if machine {
		return false
	}
	entries, _ := os.ReadDir(job.Jobs())
	for _, entry := range entries {
		if info, err := os.Stat(filepath.Join(job.Jobs(), entry.Name())); err != nil || !info.IsDir() {
			continue
		}
		receipt, err := run.ReadJSON(job.ReceiptPath(entry.Name()))
		if errors.Is(err, run.ErrLoneSurrogate) {
			return true
		}
		if receipt == nil {
			continue
		}
		if _, ok := receipt.Get("tasks").([]any); !ok {
			continue
		}
		launched := run.NewObject()
		launched.Set("launched_session", receipt.Get("seat"))
		if seat != "" && run.Seat(launched) != seat {
			continue
		}
		at, ok := receipt.Num("finished_at")
		if showHistory || !ok || !(seconds(now)-at > run.GCAge) {
			return true
		}
	}
	return false
}

func seconds(at time.Time) float64 {
	return float64(at.UnixNano()) / 1e9
}

// shown is whether a listing shows the run: any with --history, else all but what ended
// over seven days ago and needs nothing more.  An admitted error still belongs to the tick.
func shown(record *run.Object, showHistory bool, now time.Time) bool {
	state := record.Str("state")
	live := run.Going(record, now) && state == "error"
	ended := run.FirstNumber(record, "finished_at", "started_at")
	return showHistory || contains([]string{"running", "stalled", "unreadable"}, state) ||
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
	if len(name) < 14 || !digitsOnly(name[:8]) || name[8] != '-' || !digitsOnly(name[9:13]) || name[13] != '-' {
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

func digitsOnly(text string) bool {
	for _, r := range text {
		if r < '0' || r > '9' {
			return false
		}
	}
	return text != ""
}

// roundCell is `round 2/3`, with any extension.
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
		rows = append(rows, []string{entry.name(), title, run.Word(record, index, now), worker, roundCell(record), age})
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
	switch note := run.ParkedLine(record, entry.name(), now); {
	case run.GateTurnNote(record) != "":
		lines = append(lines, "  "+run.GateTurnNote(record))
	case run.BlockedNote(record, "!") != "":
		lines = append(lines, dim(run.BlockedNote(record, screen.Glyph(run.Word(record, index, now)))))
	case run.HandbackWaiting(record) != "":
		lines = append(lines, dim(run.HandbackWaiting(record)))
	case note != "":
		lines = append(lines, dim(note))
	}
	return append(lines, tail(screen, record)...)
}

// tail is the notes every format ends a run's lines with: whether it goes first, what still
// runs under it and what ended it.
func tail(screen terminal.Screen, record *run.Object) []string {
	var lines []string
	if record.Truthy("first") {
		lines = append(lines, "  first")
	}
	for _, note := range []string{run.Alive(record), run.StopNote(record)} {
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
	if note := run.GateTurnNote(record); note != "" {
		lines = append(lines, "  "+note)
	}
	if run.NeedsRecovery(record) {
		lines = append(lines, "  "+run.RecoveryReason(record)+"; ak run resume "+entry.name()+" offers recovery")
	}
	for _, note := range []string{run.BlockedNote(record, screen.Glyph(run.Word(record, index, now))),
		run.ParkedLine(record, entry.name(), now), run.HandbackWaiting(record), run.Alive(record), run.StopNote(record)} {
		if note != "" {
			lines = append(lines, dim(note))
		}
	}
	if onward := run.ContinueLine(record, dir, now); onward != "" {
		lines = append(lines, "  "+onward)
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
	line := padded(name, 40) + " " + padded(run.Field(record, "state", "?"), 11) + " " + padded(run.Text(record.Get("verdict")), 5) + " " +
		run.ExecutorLine(record) + "/" + run.Field(record, "reviewer", "?") + "  " + branch
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
	if note := run.GateTurnNote(record); note != "" {
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

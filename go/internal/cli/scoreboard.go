package cli

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tick"
)

// week is seven days in seconds: the board's two weeks end now and seven days ago.
const week = 7 * 86400.0

// The board's rows in Python's scoreboard.MEASURES order, ak's size last.
var measures = []string{"products", "ak", "tokens", "intent", "owner", "built", "waits", "merged", "checks", "parks",
	"conflicts", "sunk", "broke", "review pairs", "findings", "ak size"}

// The phases a merged change's hours are split into, each second in the first that holds it: a
// model turn, else ak's own work, else a wait; and the steps, each its phase and the column of
// runs that also counts its seconds.
var (
	parts = [3][]string{{"executor", "reviewer"}, {"done-when", "merge"},
		{"slot wait", "suite wait", "merge wait", "lander wait"}}
	steps = [][2]string{{"executor", "executor_seconds"}, {"done-when", "done_when_seconds"},
		{"reviewer", "reviewer_seconds"}, {"merge", "merge_seconds"}}
	pullRequest = regexp.MustCompile(`^.+#\d+$`) // a change named by its pull request: `owner/repo#N`
)

// A board is two weeks of history.db's ended work, as Python's scoreboard.compute reads it.
// Seats' tokens count in none of its rows: Go reads the board only before a seat has spent any it
// could count (boardHistory), and names the seats it counts nothing of.
type board struct {
	db                                 *history.DB
	now                                float64
	own                                map[string]bool // what ak's own checkout is named
	uncounted                          []string        // the seats whose tokens it counts none of
	rows, checks, findings, conflicts  []history.Row
	parks, owner, dones                []history.Row
	parksKnown, ownerKnown, donesKnown bool
	sizes                              [2][]measure // ak's committed size now and seven days ago
}

// A measure is one part of ak's size, nil where git could not tell it.
type measure struct {
	name  string
	value *int
}

// scoreboard is `--history`'s two weeks side by side, as Python's scoreboard renders them, db
// nil where no history.db stands, beside the seats whose tokens it counts none of.
func scoreboard(screen terminal.Screen, db *history.DB, uncounted []string, now time.Time) []string {
	board := readScoreboard(db, now)
	board.uncounted = uncounted
	return board.render(screen)
}

// The tick receives the same report the history screen renders, keeping its measures here.  It
// audits only where no history.db stands.
func auditScoreboard(out io.Writer) tick.AuditReport {
	return func(now time.Time) ([]string, string) {
		board := readScoreboard(nil, now)
		return board.render(terminal.For(out)), board.loss()
	}
}

func readScoreboard(db *history.DB, now time.Time) *board {
	repo := config.Repo()
	b := board{db: db, now: seconds(now), own: map[string]bool{filepath.Base(repo): true}}
	if common := gitOutput(repo, "rev-parse", "--git-common-dir"); common != nil {
		dir := strings.TrimSpace(string(common))
		if !filepath.IsAbs(dir) {
			dir = filepath.Join(repo, dir)
		}
		b.own[filepath.Base(filepath.Dir(config.Resolve(dir)))] = true
	}
	since := b.now - 2*week
	ended, _ := db.EndedRuns(since, b.now)
	for _, row := range ended {
		if state := row.Text("final_state"); run.FailedState(state) ||
			slices.Contains([]string{"pass", "exhausted", "not_needed"}, state) {
			b.rows = append(b.rows, row)
		}
	}
	b.checks, _ = db.Checks(since, b.now)
	b.findings, _ = db.Findings(since, b.now)
	b.conflicts, _ = db.Conflicts(since, b.now)
	b.parks, b.parksKnown = db.Parks(since, b.now)
	b.owner, b.ownerKnown = db.Owner(since, b.now)
	b.dones, b.donesKnown = db.Dones(since, b.now)
	before := ""
	if out := gitOutput(repo, "rev-list", "--first-parent", "-1",
		"--before="+now.Add(-7*24*time.Hour).UTC().Format("2006-01-02T15:04:05Z"), "HEAD"); out != nil {
		before = strings.TrimSpace(string(out))
	}
	b.sizes = [2][]measure{size(repo, "HEAD"), size(repo, before)}
	return &b
}

func (b *board) render(screen terminal.Screen) []string {
	current, previous := append(b.cells(b.now), sized(b.sizes[0])), append(b.cells(b.now-week), sized(b.sizes[1]))
	labelWidth := 0
	for _, label := range measures {
		labelWidth = max(labelWidth, len(label))
	}
	width := screen.ContentWidth()
	room := max(1, (width-labelWidth-4)/2)
	lines := terminal.Wrap("Scoreboard (reported tokens; size now and 7 days ago)", width)
	for i, label := range append([]string{""}, measures...) {
		left, right := terminal.Wrap("last 7 days", room), terminal.Wrap("7 days before", room)
		if i > 0 {
			left, right = terminal.Wrap(current[i-1], room), terminal.Wrap(previous[i-1], room)
		}
		for j := range max(len(left), len(right)) {
			cells := []string{"", at(left, j), at(right, j)}
			if j == 0 {
				cells[0] = label
			}
			lines = append(lines, screen.TableRow(cells, []int{labelWidth, room, room}, nil))
		}
	}
	return lines
}

// loss follows the vision's order. Without history only size has a reading.
func (b *board) loss() string {
	first := "no loss to name, since no run ended in two weeks"
	for i, part := range b.sizes[0] {
		if part.value == nil {
			continue
		}
		var previous *int
		if len(b.sizes[1]) > i {
			previous = b.sizes[1][i].value
		}
		before := "not recorded"
		if previous != nil {
			before = thousands(float64(*previous))
		}
		words := "the largest loss is ak's " + part.name + ", " + thousands(float64(*part.value)) + " against " + before + " the week before"
		if first == "no loss to name, since no run ended in two weeks" {
			first = words
		}
		if previous != nil && *part.value > *previous {
			return words
		}
	}
	return first
}

// cells are the board's cells for the week ending at end, in measures' order, all but ak's size.
func (b *board) cells(end float64) []string {
	var finished, ended []history.Row
	tokens := 0.0
	for _, row := range b.rows {
		if !b.in(number(row, "finished_at"), end) {
			continue
		}
		finished = append(finished, row)
		// a run found not needed waited and ran like any other, but delivered nothing to score
		if row.Text("final_state") != "not_needed" {
			ended = append(ended, row)
			tokens += spent(row)
		}
	}
	changes := b.changes(ended)
	tokensCell := "no tokens recorded"
	if tokens != 0 {
		tokensCell = thousands(tokens) + " tokens; 0 from seats"
	}
	if len(b.uncounted) > 0 {
		tokensCell += "; not counted: " + strings.Join(b.uncounted, ", ")
	}
	return []string{b.delivered(ended, false, tokens), b.delivered(ended, true, tokens), tokensCell, b.intent(end),
		b.asked(end), built(ended), waited(finished), b.split(changes), b.checked(changes), b.parked(end),
		b.collided(ended, end), sunk(ended, tokens), broke(ended), pairs(ended), b.weighed(ended, end)}
}

// in is whether that moment falls in the week ending at end, the last seven days' including now.
func (b *board) in(at, end float64) bool {
	return end-week <= at && (at <= end && end == b.now || at < end)
}

// delivered is the products or the ak row: what the week's runs on other repositories, or on
// ak's own checkout, delivered, and with ak's its share of every recorded token.
func (b *board) delivered(ended []history.Row, ak bool, total float64) string {
	runs, merged, firstRound, unmerged, share := 0, 0, 0, 0, 0.0
	var hours, tokens []float64
	for _, row := range ended {
		if b.own[row.Text("repo")] != ak {
			continue
		}
		runs++
		share += spent(row)
		if !row.Merged() {
			if state := row.Text("final_state"); run.FailedState(state) || state == "exhausted" {
				unmerged++
			}
			continue
		}
		merged++
		if rounds, ok := row.Num("rounds_used"); ok && rounds == 1 {
			firstRound++
		}
		if started, ok := row.Num("started_at"); ok && started <= number(row, "finished_at") {
			hours = append(hours, (number(row, "finished_at")-started)/3600)
		}
		executor, ok := row.Num("executor_tokens")
		if reviewer, known := row.Num("reviewer_tokens"); ok && known {
			tokens = append(tokens, executor+reviewer)
		}
	}
	if runs == 0 {
		return "no runs ended"
	}
	cell := fmt.Sprintf("%d runs ended; %s merged in round 1; %s ended without merging; ", runs,
		percent(float64(firstRound)/float64(runs), 0), percent(float64(unmerged)/float64(runs), 0))
	switch {
	case merged == 0:
		cell += "no merged runs"
	case len(hours) == 0:
		cell += "merge hours unknown; "
	default:
		cell += "median " + strconv.FormatFloat(quality.Median(hours), 'g', 6, 64) + " hours to merge; "
	}
	switch {
	case merged == 0:
	case len(tokens) == 0:
		cell += "median tokens per merged run unknown"
	default:
		cell += "median " + thousands(quality.Median(tokens)) + " tokens per merged run"
	}
	switch {
	case !ak:
	case total == 0:
		cell += "; no tokens recorded"
	default:
		cell += "; " + percent(share/total, 0) + " of all recorded tokens"
	}
	return cell
}

// intent is the time the owner feels: from their first message of an intent to the done that
// ends it, and to the last of its changes live, and how much of it waited on their answers.
func (b *board) intent(end float64) string {
	if !b.donesKnown {
		return "not recorded"
	}
	var took, lived []float64
	answered, waited, unknown := 0.0, 0.0, false
	for _, row := range b.dones {
		began, ok := row.Num("began")
		if !ok || !b.in(number(row, "at"), end) {
			continue
		}
		took = append(took, (number(row, "at")-began)/3600)
		waited += took[len(took)-1]
		if live, ok := row.Num("live"); ok {
			lived = append(lived, (live-began)/3600)
		}
		answer, ok := row.Num("answered")
		answered += answer
		unknown = unknown || !ok
	}
	if len(took) == 0 {
		return "no intent measured"
	}
	cell := fmt.Sprintf("%d intents measured, median %.1f hours from the owner's first message to done",
		len(took), quality.Median(took))
	if len(lived) > 0 {
		cell += fmt.Sprintf("; %d live, median %.1f hours to live", len(lived), quality.Median(lived))
	}
	if waited != 0 && !unknown {
		cell += "; " + percent(answered/(waited*3600), 1) + " of intent time waiting for the owner's answers"
	}
	return cell
}

// asked is the owner's time: what the seats asked them, what reached them, and how long they
// were waited on.
func (b *board) asked(end float64) string {
	if !b.ownerKnown {
		return "not recorded"
	}
	asked, paged := 0, 0
	var answers []float64
	for _, row := range b.owner {
		if !b.in(number(row, "at"), end) {
			continue
		}
		switch row.Text("kind") {
		case "asked":
			asked++
		case "paged":
			paged++
		case "answered":
			answers = append(answers, number(row, "waited")/3600)
		}
	}
	cell := fmt.Sprintf("%d questions asked, %d cards sent", asked, paged)
	if len(answers) > 0 {
		cell += fmt.Sprintf(", median %.1f hours waiting for an answer", quality.Median(answers))
	}
	return cell
}

// built is the week's merged runs by who built the change: a seat, whose change comes as a pull
// request's review, or a worker, each with the share that merged in round 1.  A run neither can
// be told of counts in neither.
func built(ended []history.Row) string {
	if len(ended) == 0 {
		return "no runs ended"
	}
	var merged [2]int
	var first [2]int
	for _, row := range ended {
		seat, known := bySeat(row)
		if !known || !row.Merged() {
			continue
		}
		kind := 1
		if seat {
			kind = 0
		}
		merged[kind]++
		if rounds, ok := row.Num("rounds_used"); ok && rounds == 1 {
			first[kind]++
		}
	}
	share := func(kind int) string {
		if merged[kind] == 0 {
			return "0 merged"
		}
		return fmt.Sprintf("%d merged, %s in round 1", merged[kind], percent(float64(first[kind])/float64(merged[kind]), 0))
	}
	return fmt.Sprintf("by seats, through their PRs' reviews: %s; by workers, task and fix runs: %s", share(0), share(1))
}

// bySeat is whether a seat built the run's change, its row or else its record naming a pull
// request; not known where neither is left to say.
func bySeat(row history.Row) (seat, known bool) {
	name := row.Text("change")
	if row["change"] == nil {
		record, _ := run.Read(filepath.Join(run.Runs(), row.Text("run_id")))
		if record == nil {
			return false, false
		}
		name, _ = run.ChangeName(record).(string)
	}
	return pullRequest.MatchString(name), true
}

// waited is the share of the week's run time spent waiting for a slot or a suite turn, and the
// hours in a landing line, of the runs that recorded them and whose record still ends where its
// row does; a landing check's waits are not recorded while one of them was written without.
func waited(finished []history.Row) string {
	runTime, waits, merge, lander, landerKnown := 0.0, 0.0, 0.0, 0.0, true
	for _, row := range finished {
		if row["slot_wait_seconds"] == nil || !row.Truthy("total_seconds") || !settled(row) {
			continue
		}
		runTime += number(row, "total_seconds")
		waits += number(row, "slot_wait_seconds") + number(row, "suite_wait_seconds")
		merge += number(row, "merge_wait_seconds")
		checks, ok := row.Num("lander_wait_seconds")
		lander += checks
		landerKnown = landerKnown && ok
	}
	if runTime == 0 {
		return "not recorded"
	}
	checks := "checks' waits for a suite turn are not recorded"
	if landerKnown {
		checks = fmt.Sprintf("checks waited %.1f hours for a suite turn", lander/3600)
	}
	return fmt.Sprintf("%s of run time waiting for a slot or its own suite turn; %.1f hours in a landing line, where %s",
		percent(waits/runTime, 0), merge/3600, checks)
}

// settled is whether the run's record still ends where its row does, or is gone: a run started
// again since its row ended counts waits for an attempt still going.
func settled(row history.Row) bool {
	record, _ := run.Read(filepath.Join(run.Runs(), row.Text("run_id")))
	return record == nil || run.Equal(record.Get("state"), jsonValue(row["final_state"])) &&
		run.Equal(record.Get("finished_at"), jsonValue(row["finished_at"]))
}

// changes are the runs of each change merged in the week, from either week's rows.
func (b *board) changes(ended []history.Row) [][]history.Row {
	runs := map[string][]history.Row{}
	for _, row := range b.rows {
		if started, ok := row.Num("started_at"); ok && started <= number(row, "finished_at") {
			runs[row.Change()] = append(runs[row.Change()], row)
		}
	}
	seen := map[string]bool{}
	var changes [][]history.Row
	for _, row := range ended {
		if key := row.Change(); row.Merged() && !seen[key] {
			seen[key] = true
			changes = append(changes, runs[key])
		}
	}
	return changes
}

// split is the median hours a merged change spent in model turns, in ak's own work, waiting, and
// with its seat between runs: its first start to last end less its runs' time.  A change from
// before the phase rows were kept is not recorded.
func (b *board) split(changes [][]history.Row) string {
	var medians [4][]float64
	for _, runs := range changes {
		var sums [4]float64
		first, last, going, kept := math.Inf(1), math.Inf(-1), 0.0, len(runs) > 0
		for _, row := range runs {
			hours, ok := b.hours(row)
			kept = kept && ok
			for part := range hours {
				sums[part] += hours[part]
			}
			first, last = min(first, number(row, "started_at")), max(last, number(row, "finished_at"))
			going += (number(row, "finished_at") - number(row, "started_at")) / 3600
		}
		if !kept {
			continue
		}
		sums[3] = max(0, (last-first)/3600-going)
		for part := range sums {
			medians[part] = append(medians[part], sums[part])
		}
	}
	if len(medians[0]) == 0 {
		return "no merged change"
	}
	return fmt.Sprintf("median hours per merged change: %.1f in model turns, %.1f ak's own work, %.1f waiting, "+
		"%.1f with its seat between runs", quality.Median(medians[0]), quality.Median(medians[1]),
		quality.Median(medians[2]), quality.Median(medians[3]))
}

// hours are a run's hours in each part, read from its phase rows so that no second is in two;
// false for a run whose step columns count seconds its step rows do not hold, begun before the
// rows were kept.  Steps alone are compared: a wait's column counts monotonic seconds that a
// clock correction sets apart from its row.
func (b *board) hours(row history.Row) ([3]float64, bool) {
	phases, _ := b.db.Phases(row.Text("run_id"))
	var ended []history.Row
	var edges []float64
	kept, counted := 0.0, 0.0
	for _, phase := range phases {
		if phase["ended_at"] == nil {
			continue
		}
		ended = append(ended, phase)
		edges = append(edges, number(phase, "started_at"), number(phase, "ended_at"))
		if slices.ContainsFunc(steps, func(step [2]string) bool { return step[0] == phase.Text("phase") }) {
			kept += number(phase, "ended_at") - number(phase, "started_at")
		}
	}
	for _, step := range steps {
		counted += number(row, step[1])
	}
	var hours [3]float64
	if counted > kept+1 {
		return hours, false
	}
	slices.Sort(edges)
	edges = slices.Compact(edges)
	for i := 1; i < len(edges); i++ {
		start, end := edges[i-1], edges[i]
		for part, names := range parts {
			if slices.ContainsFunc(ended, func(phase history.Row) bool {
				return slices.Contains(names, phase.Text("phase")) && number(phase, "started_at") <= start &&
					end <= number(phase, "ended_at")
			}) {
				hours[part] += (end - start) / 3600
				break
			}
		}
	}
	return hours, true
}

// checked is the suite runs and summed check hours per merged change; not recorded without a row.
func (b *board) checked(changes [][]history.Row) string {
	ids := map[string]bool{}
	for _, runs := range changes {
		for _, row := range runs {
			ids[row.Text("run_id")] = true
		}
	}
	suites := map[[4]any]bool{}
	pieces, elapsed := 0, 0.0
	for _, row := range b.checks {
		if !ids[row.Text("run_id")] {
			continue
		}
		pieces++
		if strings.HasPrefix(row.Text("command"), "AK_SHARD=") {
			suites[[4]any{row["run_id"], row["round"], row["kind"], row["tree"]}] = true
		}
		finished, ok := row.Num("finished_at")
		if started, known := row.Num("started_at"); ok && known {
			elapsed += finished - started
		}
	}
	if pieces == 0 {
		return "not recorded"
	}
	return fmt.Sprintf("%.2f suite runs and %.2f check hours per merged change",
		float64(len(suites))/float64(len(changes)), elapsed/3600/float64(len(changes)))
}

// parked is how many runs the park stopped in the week.
func (b *board) parked(end float64) string {
	if !b.parksKnown {
		return "not recorded"
	}
	parked := 0
	for _, row := range b.parks {
		if b.in(number(row, "parked_at"), end) {
			parked++
		}
	}
	return fmt.Sprintf("%d runs stopped by the park to wait on an older change's lines", parked)
}

// collided is the share of the week's merged changes that ever conflicted, and the files that
// conflicted twice or more by their conflicts' own dates.
func (b *board) collided(ended []history.Row, end float64) string {
	merged, met := map[[2]string]bool{}, 0
	for _, row := range ended {
		if row["changed_lines"] != nil {
			merged[[2]string{row.Text("repo"), row.Change()}] = true
		}
	}
	type file struct {
		repo, path string
		count      int
		added      bool
	}
	seen, counts := map[[2]string]bool{}, map[[2]string]*file{}
	for _, row := range b.conflicts {
		at := number(row, "at")
		if at <= end && (end == b.now || at < end) {
			seen[[2]string{row.Text("repo"), row.Text("change")}] = true
		}
		if !b.in(at, end) {
			continue
		}
		key := [2]string{row.Text("repo"), row.Text("path")}
		if counts[key] == nil {
			counts[key] = &file{key[0], key[1], 0, true}
		}
		added, ok := row.Num("added_only")
		counts[key].count++
		counts[key].added = counts[key].added && ok && added == 1
	}
	if len(merged) == 0 && len(counts) == 0 {
		return "no merged change"
	}
	for key := range merged {
		if seen[key] {
			met++
		}
	}
	cell := "no merged change"
	if len(merged) > 0 {
		cell = percent(float64(met)/float64(len(merged)), 0) + " of merged changes met a conflict"
	}
	var files []*file
	for _, each := range counts {
		if each.count >= 2 {
			files = append(files, each)
		}
	}
	sort.Slice(files, func(i, j int) bool {
		return cmp.Or(cmp.Compare(files[j].count, files[i].count), strings.Compare(files[i].repo, files[j].repo),
			strings.Compare(files[i].path, files[j].path)) < 0
	})
	for _, each := range files[:min(3, len(files))] {
		cell += fmt.Sprintf("; %s/%s: %d conflicts", each.repo, each.path, each.count)
		if each.added {
			cell += " (added lines only)"
		}
	}
	return cell
}

// sunk is the week's tokens that bought no merge: every ended run's that delivered nothing.
func sunk(ended []history.Row, total float64) string {
	if total == 0 {
		return "no tokens recorded"
	}
	wasted := 0.0
	for _, row := range ended {
		if !row.Merged() {
			wasted += spent(row)
		}
	}
	return fmt.Sprintf("%s of the week's tokens, %s, went to runs that never merged", percent(wasted/total, 0), thousands(wasted))
}

// broke is the week's merged changes that broke after review passed them: their tests red at
// landing, or main's checks or live health after their merge, as each run's row records it; a
// row from before breaks were recorded is unknown until one is recorded on it.
func broke(ended []history.Row) string {
	merged, known, after, landing, flakes := 0, 0, 0, 0, 0
	for _, row := range ended {
		if !row.Merged() {
			continue
		}
		merged++
		if row["landing_breaks"] == nil && row["broke_after_merge"] == nil {
			continue
		}
		known++
		after += count(row.Truthy("broke_after_merge"))
		landing += count(row.Truthy("landing_breaks"))
		flakes += count(row.Truthy("landing_flakes"))
	}
	if merged == 0 {
		return "no merged change"
	}
	cell := fmt.Sprintf("%d of %d merged changes broke main or live after merge; %d went red at landing; %d more were flakes",
		after, known, landing, flakes)
	if merged > known {
		cell += fmt.Sprintf("; %d merged before breaks were recorded", merged-known)
	}
	return cell
}

// pairs is the week's merged changes, each by its last run, by their recorded review pair;
// unknown pairs count in none, and unknown landing results in no landing share.
func pairs(ended []history.Row) string {
	last := map[string]history.Row{}
	for _, row := range ended {
		if previous, ok := last[row.Change()]; row.Merged() && (!ok || number(row, "finished_at") >= number(previous, "finished_at")) {
			last[row.Change()] = row
		}
	}
	paired := 0
	shares := map[string][3]int{} // per pair: changes, landings known, landings red
	for _, row := range last {
		if row["review_pair"] == nil {
			continue
		}
		paired++
		share := shares[row.Text("review_pair")]
		share[0]++
		if row["landing_breaks"] != nil {
			share[1]++
			share[2] += count(row.Truthy("landing_breaks"))
		}
		shares[row.Text("review_pair")] = share
	}
	if paired == 0 {
		return "not recorded"
	}
	landing := func(pair string) string {
		if shares[pair][1] == 0 {
			return "landing not recorded"
		}
		return percent(float64(shares[pair][2])/float64(shares[pair][1]), 0) + " went red at landing"
	}
	return fmt.Sprintf("%s self-reviewed (%s); %s reviewed by another model of the same provider (%s); another provider: %s",
		percent(float64(shares["self"][0])/float64(paired), 0), landing("self"),
		percent(float64(shares["same provider"][0])/float64(paired), 0), landing("same provider"), landing("other provider"))
}

// weighed is the week's weighed findings: the blocking ones, those disputed, conceded or raised
// again, and those let go on the week's merged changes, a finding following its change's merge
// week, and how many of those sat on a change that later broke.
func (b *board) weighed(ended []history.Row, end float64) string {
	merged, broken := map[[2]string]bool{}, map[[2]string]bool{}
	for _, row := range ended {
		if row.Merged() {
			key := [2]string{row.Text("repo"), row.Change()}
			merged[key] = true
			broken[key] = broken[key] || row.Truthy("broke_after_merge")
		}
	}
	weighed, blocking, disputed, conceded, raised, letGo, letGoBroke := 0, 0, 0, 0, 0, 0, 0
	for _, row := range b.findings {
		dropped := slices.Contains([]string{"dropped", "conceded"}, row.Text("outcome"))
		if b.in(number(row, "at"), end) {
			weighed++
			disputed += count(row["outcome"] != nil)
			conceded += count(dropped)
			if row.Text("kind") == "finding" {
				blocking++
				raised += int(number(row, "raised_again"))
			}
		}
		if key := [2]string{row.Text("repo"), row.Change()}; (row.Text("kind") == "follow-up" || dropped) && merged[key] {
			letGo++
			letGoBroke += count(broken[key])
		}
	}
	if weighed == 0 && letGo == 0 {
		return "not recorded"
	}
	return fmt.Sprintf("%d blocking; %d disputed; %d of %d conceded; %d of %d raised again; %d let go; "+
		"%d of %d on a change that broke main or live after merge",
		blocking, disputed, conceded, disputed, raised, blocking, letGo, letGoBroke, letGo)
}

// size is ak's committed size at that ref: its code lines and its README's and AGENTS.md's words,
// nil where git tells none of them.
func size(repo, ref string) []measure {
	if ref == "" {
		return nil
	}
	code := gitOutput(repo, "grep", "-I", "-h", "--no-color", "-e", "^", ref, "--",
		"agentkit/", "bin/", "hooks/", "adapters/", "tools/", "install.sh")
	readme, agents := gitOutput(repo, "show", ref+":README.md"), gitOutput(repo, "show", ref+":AGENTS.md")
	if code == nil && readme == nil && agents == nil {
		return nil
	}
	var parts []measure
	for _, part := range []struct {
		value []byte
		name  string
		count func([]byte) int
	}{
		{code, "code lines", func(text []byte) int { return bytes.Count(text, []byte("\n")) }},
		{readme, "README words", wordCount},
		{agents, "AGENTS.md words", wordCount},
	} {
		if part.value == nil {
			parts = append(parts, measure{part.name, nil})
		} else {
			count := part.count(part.value)
			parts = append(parts, measure{part.name, &count})
		}
	}
	return parts
}

// sized is ak's size in the board's words.
func sized(parts []measure) string {
	if parts == nil {
		return "size unavailable"
	}
	var words []string
	for _, part := range parts {
		word := part.name + " unknown"
		if part.value != nil {
			word = fmt.Sprintf("%d %s", *part.value, part.name)
		}
		words = append(words, word)
	}
	return strings.Join(words, ", ")
}

// sizeLines are a line per repository with a finished run, as Python's size_summary_line writes
// it: the median rounds its last twenty tasks took, overall, over long tasks and over
// many-pointed ones, so the next task is sized from them, and the AGENTS.md its last run's
// workers were handed against the most a harness reads of it.
func sizeLines(db *history.DB) []string {
	repos, _ := db.FinishedRepos()
	var lines []string
	for _, each := range repos {
		repo := each.Text("repo")
		tasks, _ := db.Sized(repo, 20)
		if len(tasks) == 0 {
			continue
		}
		var overall, words, points []float64
		for _, task := range tasks {
			rounds := number(task, "rounds_used")
			overall = append(overall, rounds)
			if value, ok := task.Num("task_words"); ok && value > 400 {
				words = append(words, rounds)
			}
			if value, ok := task.Num("task_points"); ok && value > 3 {
				points = append(points, rounds)
			}
		}
		line := fmt.Sprintf("%s: last 20 tasks: %s · over 400 words: %s · over 3 points: %s",
			repo, medianRounds(overall), medianRounds(words), medianRounds(points))
		if rules, _ := db.RulesBytes(repo); len(rules) > 0 && rules[0].Truthy("rules_bytes") {
			line += " · AGENTS.md " + thousands(number(rules[0], "rules_bytes")) + " bytes"
			if limit, _ := config.ReadLimit(); limit > 0 {
				line += " of " + thousands(float64(limit))
			}
		}
		lines = append(lines, line)
	}
	return lines
}

func medianRounds(taken []float64) string {
	if len(taken) == 0 {
		return "–"
	}
	return "median " + strconv.FormatFloat(quality.Median(taken), 'g', 6, 64) + " rounds"
}

// number is a row's number, 0 for none.
func number(row history.Row, column string) float64 {
	value, _ := row.Num(column)
	return value
}

func count(yes bool) int {
	if yes {
		return 1
	}
	return 0
}

// jsonValue is a row's value as a record would hold it, for run.Equal.
func jsonValue(value any) any {
	switch value := value.(type) {
	case int64:
		return run.Float(float64(value))
	case float64:
		return run.Float(value)
	}
	return value
}

// spent is the tokens a run's turns reported.
func spent(row history.Row) float64 {
	return number(row, "executor_tokens") + number(row, "reviewer_tokens")
}

// percent is a share as Python's `{:.Nf%}` writes it.
func percent(share float64, digits int) string {
	return strconv.FormatFloat(share*100, 'f', digits, 64) + "%"
}

// thousands is a number as Python's `{:,}` writes it, an integral float without its `.0`.
func thousands(value float64) string {
	whole, fraction, _ := strings.Cut(strconv.FormatFloat(math.Abs(value), 'f', -1, 64), ".")
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	if value < 0 {
		whole = "-" + whole
	}
	if fraction != "" {
		return whole + "." + fraction
	}
	return whole
}

func at(lines []string, i int) string {
	if i < len(lines) {
		return lines[i]
	}
	return ""
}

func wordCount(text []byte) int {
	return len(strings.FieldsFunc(strings.ToValidUTF8(string(text), "�"), config.Space))
}

// gitOutput is git's stdout in that repository, or nil where it cannot answer in ten
// seconds; `git grep` finding nothing is an answer.
func gitOutput(repo string, args ...string) []byte {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "git", append([]string{"-C", repo}, args...)...).Output()
	var exit *exec.ExitError
	if err == nil || args[0] == "grep" && errors.As(err, &exit) && exit.ExitCode() == 1 {
		return out
	}
	return nil
}

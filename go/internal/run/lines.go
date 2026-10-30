package run

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/host"
)

// Text is a value as Python's str() writes it: None, True, a number as Python holds it.
func Text(value any) string {
	switch value := value.(type) {
	case nil:
		return "None"
	case bool:
		if value {
			return "True"
		}
		return "False"
	case string:
		return value
	case Number:
		switch text := written(value); text {
		case "NaN":
			return "nan"
		case "Infinity":
			return "inf"
		case "-Infinity":
			return "-inf"
		default:
			return text
		}
	}
	return repr(value)
}

// repr is a value as Python's repr() writes it inside a list or a dict.
func repr(value any) string {
	switch value := value.(type) {
	case string:
		quote := "'"
		if strings.Contains(value, "'") && !strings.Contains(value, `"`) {
			quote = `"`
		}
		var out strings.Builder
		for _, r := range value {
			switch {
			case r == '\\' || string(r) == quote:
				out.WriteString(`\` + string(r))
			case r == '\n':
				out.WriteString(`\n`)
			case r == '\r':
				out.WriteString(`\r`)
			case r == '\t':
				out.WriteString(`\t`)
			case unicode.IsPrint(r):
				out.WriteRune(r)
			case r < 0x100:
				fmt.Fprintf(&out, `\x%02x`, r)
			case r < 0x10000:
				fmt.Fprintf(&out, `\u%04x`, r)
			default:
				fmt.Fprintf(&out, `\U%08x`, r)
			}
		}
		return quote + out.String() + quote
	case []any:
		parts := make([]string, len(value))
		for i, item := range value {
			parts[i] = repr(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *Object:
		parts := make([]string, len(value.keys))
		for i, key := range value.keys {
			parts[i] = repr(key) + ": " + repr(value.values[key])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return Text(value)
}

// Field is the key's value as text, or fallback where the record has no such key.
func Field(record *Object, key, fallback string) string {
	if !record.Has(key) {
		return fallback
	}
	return Text(record.Get(key))
}

// firstText is the first of the keys holding a true value, as text, else fallback.
func firstText(record *Object, fallback string, keys ...string) string {
	for _, key := range keys {
		if record.Truthy(key) {
			return Text(record.Get(key))
		}
	}
	return fallback
}

// words is text on one line, one space between its words.
func words(text string) string {
	return strings.Join(strings.Fields(text), " ")
}

func clock(at float64, layout string) string {
	return time.Unix(0, int64(at*1e9)).Format(layout)
}

// AgeSeconds is what the age column reads: an interruption's age, a live run's, else how
// long it ran.
func AgeSeconds(record *Object, now time.Time) float64 {
	started := FirstNumber(record, "started_at")
	switch {
	case NeedsRecovery(record):
		return max(0, seconds(now)-firstNonZero(FirstNumber(record, "interrupted_at"), started, seconds(now)))
	case Active(record):
		return max(0, seconds(now)-firstNonZero(started, seconds(now)))
	case started == 0:
		return 0
	}
	return max(0, FirstNumber(record, "finished_at")-started)
}

func firstNonZero(values ...float64) float64 {
	for _, value := range values {
		if value != 0 {
			return value
		}
	}
	return 0
}

// ResumeAge names, for an hour, the resume that continued a run, in the age column's place.
func ResumeAge(record *Object, now time.Time) string {
	note := record.Dict("resume_notice")
	if note == nil {
		return ""
	}
	at, ok := note.Num("at")
	if age := seconds(now) - at; !ok || !(0 <= age && age <= 3600) {
		return ""
	}
	if note.Truthy("restarted") {
		return "resumed " + clock(at, "15:04") + " · turn restarted"
	}
	role := firstText(note, "executor", "role")
	what := "the " + role
	if role == "executor" || role == "fixer" || role == "reviewer" {
		what += "'s turn"
	}
	return "resumed " + clock(at, "15:04") + " · continued " + what
}

// ParkedLine is the dim line under an error: its scheduled retry, or who an unscheduled one
// waits for -- nobody, once it is its seat's.
func ParkedLine(record *Object, name string, now time.Time) string {
	if record.Str("state") != "error" {
		return ""
	}
	reason := []rune(words(firstText(record, "no reason was recorded", "error")))
	parked := "run " + name + " parked: " + string(reason[:min(len(reason), 300)])
	if record.Truthy("handed_back") || record.Truthy("handback_pending") || record.Truthy("recovery_acknowledged_at") {
		parked = "error: " + string(reason[:min(len(reason), 300)])
	}
	at, ok := record.Num("error_retry_at")
	admission := TickAdmission(record, now)
	switch {
	case admission == "" || !ok:
		return parked
	case at <= seconds(now):
		return "error · retry due · " + admission
	}
	return "error · retry " + clock(at, "15:04") + " · " + admission
}

// BlockedNote is `<glyph> blocked · <why>` under a run the orchestrator has to write a new
// task for: a blocked run is final, so it offers no number to resume from.
func BlockedNote(record *Object, glyph string) string {
	if record.Str("state") != "blocked" {
		return ""
	}
	return glyph + " blocked · " + words(firstText(record, "the task cannot be completed as written", "error"))
}

// HandbackWaiting is the line under a run whose ending waits for a seat the owner closed.
func HandbackWaiting(record *Object) string {
	if !record.Truthy("handback_pending") || !record.Truthy("handback_wait_reason") {
		return ""
	}
	return "hand-back waiting: " + Text(record.Get("handback_wait_reason"))
}

// GateTurnNote says a running run waits for a heavy suite turn.
func GateTurnNote(record *Object) string {
	turn := record.Dict("gate_turn")
	if record.Str("state") != "running" || turn == nil || !Equal(turn.Get("pid"), record.Get("pid")) {
		return ""
	}
	return "waiting for a heavy suite turn"
}

// StopNote is what a cap or a kill that ended the run said, in its own words.
func StopNote(record *Object) string {
	if record.Str("state") == "stopped" {
		if record.Truthy("lease_restarted") {
			return "stopped · started again as " + Text(record.Get("lease_restarted"))
		}
		return "stopped · " + words(firstText(record, "stopped by the user", "error"))
	}
	err := words(firstText(record, "", "error"))
	if lowered := strings.ToLower(err); strings.Contains(lowered, "killed") || strings.Contains(lowered, "memory cap") {
		return err
	}
	return ""
}

// StallSummary is `stalled 2× (<step>), recovered` for a running run with stalls.
func StallSummary(record *Object) string {
	stalls := record.List("stalls")
	if record.Str("state") != "running" || len(stalls) == 0 {
		return ""
	}
	step := ""
	if last, ok := stalls[len(stalls)-1].(*Object); ok {
		step = strings.TrimSpace(firstText(last, "", "step"))
	}
	if step == "" {
		return fmt.Sprintf("stalled %d×, recovered", len(stalls))
	}
	return fmt.Sprintf("stalled %d× (%s), recovered", len(stalls), step)
}

// DeathLines are one line per recorded death.
func DeathLines(record *Object) []string {
	var lines []string
	for _, entry := range record.List("deaths") {
		death, ok := entry.(*Object)
		if !ok {
			continue
		}
		when := "?"
		if at, ok := death.Num("at"); ok {
			when = clock(at, "2006-01-02 15:04:05")
		}
		parked := ""
		if death.Truthy("parked") {
			parked = " parked"
		}
		lines = append(lines, fmt.Sprintf("  death %s pid %s%s: %s", when, Text(death.Get("pid")), parked, firstText(death, "", "reason")))
	}
	return lines
}

// WorkspaceLocation is `present`, or what a missing checkout still leaves behind: its branch,
// unless a stop without --keep, a merge, a run found not needed or a seat's stop took it.
func WorkspaceLocation(record *Object, present bool) string {
	state := record.Str("state")
	switch {
	case present:
		return "present"
	case state == "stopped" && !record.Truthy("stop_kept") || state == "not_needed" ||
		record.Truthy("merged") || record.Truthy("branch_removed"):
		return "removed; branch removed"
	}
	return "removed; branch/PR retained"
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// worktree is the run's checkout as a path, "" for none.
func worktree(record *Object) string {
	if record.Truthy("worktree") {
		return Text(record.Get("worktree"))
	}
	return ""
}

// TaskMaxRounds is a change's round budget across all its runs: past it, split or re-scope.
const TaskMaxRounds = 3

var pullRequest = regexp.MustCompile(`^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$`)

// prKey is one pull request however its URL was spelled, "" for no pull request URL.
func prKey(value any) string {
	url, _ := value.(string)
	found := pullRequest.FindStringSubmatch(strings.TrimSpace(url))
	if found == nil {
		return ""
	}
	return strings.ToLower(found[1]) + "/" + strings.ToLower(found[2]) + "#" + found[3]
}

// changeOf is the change a run belongs to: the one it inherited at a `from:` launch, else its own.
func changeOf(record *Object) any {
	if record.Truthy("change") {
		return record.Get("change")
	}
	return record.Get("run_id")
}

// roundsSpent is the rounds a run spent: each with a verdict, and the one under way on a run
// still going.
func roundsSpent(record *Object, now time.Time) int {
	recorded := len(record.List("round_summaries"))
	begun := FirstNumber(record, "step_round")
	if pending := record.Dict("review_pending"); pending != nil {
		begun = max(begun, FirstNumber(pending, "round"))
	}
	if begun > float64(recorded) && Going(record, now) {
		return recorded + 1
	}
	return recorded
}

// lineageCap is the rounds that run may have in all: the change's budget less what its other
// runs, on its pull request or its change, spent.
func lineageCap(record *Object, dir string, now time.Time) int {
	wanted := prKey(record.Get(firstKey(record, "pr", "review_pr")))
	change, spent := changeOf(record), 0
	for _, other := range Dirs() {
		if filepath.Base(other) == filepath.Base(dir) {
			continue
		}
		state, _ := Read(other)
		if state != nil && (wanted != "" && (prKey(state.Get("pr")) == wanted || prKey(state.Get("review_pr")) == wanted) ||
			change != nil && Equal(changeOf(state), change)) {
			spent += roundsSpent(state, now)
		}
	}
	return max(0, TaskMaxRounds-spent)
}

// judged is a review that failed a tree it names, with a done-when value.
func judged(review *Object) bool {
	return review != nil && review.Str("verdict") == "FAIL" && review.Get("done_when") != nil &&
		(review.Has("head_sha") || review.Has("tree_sha"))
}

// ContinueLine is the way on from a stall, a FAIL at its round budget while its change has
// rounds left, or a FAIL in integration with rounds left.
func ContinueLine(record *Object, dir string, now time.Time) string {
	if !record.Truthy("run_id") {
		return ""
	}
	id := Text(record.Get("run_id"))
	summaries := record.List("round_summaries")
	budget := FirstNumber(record, "rounds")
	fail := record.Str("state") == "fail" && !record.Truthy("review_pr") && isDir(worktree(record))
	switch {
	case record.Str("state") == "stalled":
		return "continue: ak run resume " + id
	case fail && budget > 0 && float64(len(summaries)) >= budget:
		// up to the change's budget across its runs and no further: past it the task is
		// split or redesigned instead
		if capped := lineageCap(record, dir, now); budget < float64(capped) {
			return fmt.Sprintf("continue: ak run resume %s --rounds %d", id, capped)
		}
		return ""
	}
	// a FAIL in integration: its branch, base and budget saved, its last word from delivery
	for _, key := range []string{"branch", "base", "base_sha", "rounds", "merge_note"} {
		fail = fail && record.Truthy(key)
	}
	log, err := os.ReadFile(filepath.Join(dir, "log.txt"))
	if !fail || err != nil || !strings.Contains(string(log), "not merged:") || float64(len(summaries)) >= budget {
		return ""
	}
	var last *Object
	if len(summaries) > 0 {
		last, _ = summaries[len(summaries)-1].(*Object)
	}
	if judged(last) || !judged(record.Dict("review")) {
		return "continue: ak run resume " + id
	}
	return ""
}

// Alive is `3 processes · 1.2 GB` under an unfinished run: its scope's cgroup where it has
// one, else every process carrying its marker and its loop.  A finished run owns nothing.
func Alive(record *Object) string {
	if Ended(record) {
		return ""
	}
	if scope := scopeDir(record.Str("scope")); scope != "" {
		if count, bytes, ok := host.CgroupUse(scope); ok {
			return aliveText(count, bytes)
		}
	}
	var pids []int
	if record.Truthy("run_id") {
		pids = host.Marked(filepath.Join(Runs(), Text(record.Get("run_id"))))
	}
	if pid, ok := record.Int("pid"); ok && pid > 0 && ProcessActive(record) && !slices.Contains(pids, pid) {
		pids = append(pids, pid)
	}
	resident := int64(0)
	for _, pid := range pids {
		if bytes, ok := host.Resident(pid); ok {
			resident += bytes
		}
	}
	if len(pids) == 0 && !isDir("/proc") {
		return "" // without /proc there is no scan to believe, and no zero to show
	}
	return aliveText(len(pids), resident)
}

func scopeDir(scope string) string {
	if scope == "" || scope == "none" || strings.HasPrefix(scope, "none (") {
		return ""
	}
	for _, suffix := range []string{".scope", ".service"} {
		name := scope
		if !strings.HasSuffix(name, suffix) {
			name += suffix
		}
		if path := filepath.Join(host.RunsCgroup(), name); isDir(path) {
			return path
		}
	}
	return ""
}

func aliveText(count int, resident int64) string {
	noun := "processes"
	if count == 1 {
		noun = "process"
	}
	mb := float64(resident) / (1024 * 1024)
	memory := "0 KB"
	switch {
	case mb >= 1024:
		memory = host.G(mb, true) + " GB"
	case mb >= 1:
		memory = strconv.FormatFloat(mb, 'f', 0, 64) + " MB"
	case mb*1024 >= 1:
		memory = strconv.FormatFloat(mb*1024, 'f', 0, 64) + " KB"
	}
	return fmt.Sprintf("%d %s · %s", count, noun, memory)
}

// ProcessActive is whether the run's own loop still runs: its pid alive with the identity
// the record saved, or for an old record, born before it and running `ak run`.
func ProcessActive(record *Object) bool {
	pid, ok := record.Int("pid")
	if !ok || !host.Alive(pid) {
		return false
	}
	current, ok := host.ReadIdentity(pid)
	if !ok {
		// a zombie still answers kill(0); an unreadable /proc is no proof of death
		stat, ok := host.ReadStat(pid)
		return !ok || !stat.Exited()
	}
	if saved := record.Dict("process_identity"); saved != nil && len(saved.keys) > 0 {
		ticks, ok := saved.Int("ticks")
		return saved.Str("boot") == current.Boot && ok && int64(ticks) == current.Ticks
	}
	if started := FirstNumber(record, "started_at"); started != 0 && current.StartedAt > started+1 {
		return false
	}
	command, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cmdline")
	if err != nil {
		return true
	}
	args := strings.Split(string(command), "\x00")
	for i, arg := range args {
		if filepath.Base(arg) == "ak" && i+1 < len(args) && args[i+1] == "run" {
			return true
		}
	}
	return false
}

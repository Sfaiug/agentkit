package seat

import (
	"cmp"
	"context"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/terminal"
)

// layoutWidth is terminal.layout_width: past it the margin grows, never the text.
const layoutWidth = 120

// A flight is what one other seat, or a run launched from none, has going on a checkout.
type flight struct {
	name         string
	lines, files []string
}

// File is Python's orch.cmd_project of the seat by that name: what it says wrapped to the columns
// given, a refusal in Python's words, or false where the verb is Python's.  Everything is read
// before the record changes, so a read Go cannot make files nothing and prints nothing wrong.
func File(given, named string, columns int, now time.Time) (string, bool, error) {
	name, _, err := config.ResolveSession(given)
	if err != nil || !checkoutsSeen() {
		return "", false, nil
	}
	stands := sync.OnceValue(listed)
	repo, known, err := checkoutNamed(named, stands)
	if !known || err != nil {
		return "", known, err
	}
	flights, known := inFlight(name, repo, stands, now)
	state := filepath.Join(config.Home(), "state")
	// a record Python cannot parse it refuses in the parser's own words
	_, unread := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if !known || unread != nil && !errors.Is(unread, fs.ErrNotExist) {
		return "", false, nil
	}
	if err := config.EnsureDirs(); err != nil {
		return "", true, err
	}
	kept := false
	err = notify.Held(context.Background(), name, func(current string) error {
		name = current
		return update(state, current, func(data *run.Object) bool {
			kept = true
			return set([]field{{"repo", repo}, {"filed", true}})(data)
		})
	})
	if err != nil {
		return "", true, err
	}
	if !kept {
		return "", true, Refusal("no orchestrator session " + commandhelp.Quote(name))
	}
	return filedLines(name, base(repo), flights, min(columns, layoutWidth)), true, nil
}

// checkoutNamed is the checkout a name in any case, a path or a worktree finds; a name spelled
// exactly wins over one that differs only in case.  False where only Python can say: casefold
// past ASCII, which Go's standard library cannot do (`ß` is `ss`), and another user's `~`.
func checkoutNamed(named string, stands func() []stand) (string, bool, error) {
	found := checkouts(stands)
	if at := slices.IndexFunc(found, func(path string) bool { return base(path) == named }); at >= 0 {
		return found[at], true, nil
	}
	if !ascii(named) || slices.ContainsFunc(found, func(path string) bool { return !ascii(base(path)) }) || config.OtherHome(named) {
		return "", false, nil
	}
	alike := slices.DeleteFunc(slices.Clone(found), func(path string) bool { return !strings.EqualFold(base(path), named) })
	if len(alike) > 1 {
		return "", true, Refusal("ambiguous checkout: " + commandhelp.Quote(named) + " (checkouts: " + strings.Join(alike, ", ") + ")")
	}
	if len(alike) == 1 {
		return alike[0], true, nil
	}
	if named != "" { // no path at all, where Absolute would read the current directory
		if repo := checkoutOf(config.Absolute(named), stands); repo != "" {
			return repo, true, nil
		}
	}
	listing := cmp.Or(strings.Join(found, ", "), "none")
	return "", true, Refusal("not a checkout: " + commandhelp.Quote(named) + " (checkouts: " + listing + ")")
}

func ascii(text string) bool {
	return !strings.ContainsFunc(text, func(r rune) bool { return r > unicode.MaxASCII })
}

// checkouts are the projects' checkouts by name (orch.checkouts).
func checkouts(stands func() []stand) []string {
	var found []string
	for _, each := range stands() {
		found = append(found, each.project)
	}
	slices.SortFunc(found, func(a, b string) int { return cmp.Or(cmp.Compare(base(a), base(b)), cmp.Compare(a, b)) })
	return slices.Compact(found)
}

// inFlight is orch.in_flight, by name: what the other seats have on the checkout, each filed
// under it or with a going run on it, and the going runs launched from none; or false where a
// record, a plan or a path cannot be read as Python does.
func inFlight(name, repo string, stands func() []stand, now time.Time) ([]flight, bool) {
	target := checkoutOf(repo, stands)
	if target == "" {
		return nil, true
	}
	if _, err := os.ReadDir(run.Runs()); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, false
	}
	filed := map[string]bool{}
	for _, path := range config.SeatFiles() {
		record, err := run.ReadJSON(path)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, false
		}
		if record != nil && !record.Has(config.Renamed) && checkoutOf(record.Str("repo"), stands) == target {
			seat, _ := sessionFile(filepath.Base(path))
			filed[seat] = true
		}
	}
	changing := map[string][]string{}
	for seat := range filed {
		changing[seat] = nil
	}
	delete(changing, name)
	var rows []flight
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, false
		}
		if record == nil {
			continue
		}
		seat := run.Seat(record)
		if seat == "" && (record.Truthy("launched_session") || record.Truthy("session")) {
			return nil, false // a rename chain Python refuses
		}
		if seat == name || !run.Going(record, now) || run.SmokeRun(record) || checkoutOf(record.Str("repo"), stands) != target {
			continue
		}
		files, known := changedFiles(dir, record)
		if !known {
			return nil, false
		}
		if seat != "" {
			changing[seat] = append(changing[seat], files...)
		} else if len(files) > 0 {
			rows = append(rows, flight{"run " + filepath.Base(dir), nil, files})
		}
	}
	here := func(path string) bool { return checkoutOf(path, stands) == target }
	for seat, files := range changing {
		lines, err := plan.OpenLines(seat, filed[seat], here)
		if err != nil {
			return nil, false
		}
		if len(lines) > 0 || len(files) > 0 {
			rows = append(rows, flight{seat, lines, files})
		}
	}
	slices.SortFunc(rows, func(a, b flight) int { return cmp.Compare(a.name, b.name) })
	return rows, true
}

// changedFiles is orch.changed_files: the tracked paths a run's worktree changes against its base,
// committed or not, none where git cannot say; before it has a worktree, its saved task's `files:`.
// False for a path Go cannot print as Python reads it.
func changedFiles(dir string, record *run.Object) ([]string, bool) {
	tree, from := record.Str("worktree"), record.Str("base_sha")
	if info, err := os.Stat(tree); tree == "" || from == "" || err != nil || !info.IsDir() {
		return task.SavedFiles(filepath.Join(dir, "task.md")), true
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "git", "-C", tree, "diff", "--name-only", "-z", "--no-renames", from, "--").Output()
	if err != nil {
		return nil, true
	}
	return strings.FieldsFunc(string(out), func(r rune) bool { return r == 0 }), utf8.Valid(out)
}

// filedLines is what filing says: the seat's new place, then what else is in flight there, in the
// room a line has.
func filedLines(name, project string, flights []flight, width int) string {
	said := []string{"filed " + name + " under " + project}
	if len(flights) == 0 {
		return said[0] + "\nnothing else in flight on " + project
	}
	said = append(said, "in flight on "+project+", plan around it:")
	room := width - 4
	wrapped := func(indent, text string, room int) {
		for _, part := range terminal.Wrap(text, room) {
			said = append(said, indent+part)
		}
	}
	for _, row := range flights {
		wrapped("  ", row.name, room+2)
		for _, line := range row.lines {
			wrapped("    ", "plan: "+line, room)
		}
		if len(row.files) > 0 {
			slices.Sort(row.files)
			wrapped("    ", "changing: "+strings.Join(slices.Compact(row.files), ", "), room)
		}
	}
	return strings.Join(said, "\n")
}

// Package waitfact is what ends a seat's `ak wait`, as Python's watch.wait_fact and work_live
// read it: the one home of the line `ak wait` refuses an ended wait with and the tick tells a
// seat whose wait ended.
package waitfact

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/gh"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// ErrPython is a fact only Python reads yet.
var ErrPython = errors.New("left to Python")

// Going is transitions.going as Go reads it: an exhausted run's is Python's (`exhausted_wait`).
func Going(record *run.Object, now time.Time) (bool, error) {
	if record.Str("state") == "exhausted" {
		return false, ErrPython
	}
	return run.Going(record, now), nil
}

// Run is wait_fact for a run: over, with the line saying how and the run whose ending that is,
// once it is no longer going, or once the run its task was started again as is not.
func Run(on string, now time.Time) (bool, string, string, error) {
	for seen := []string{on}; ; seen = append(seen, on) {
		record, err := run.Read(filepath.Join(run.Runs(), on))
		switch {
		case errors.Is(err, run.ErrLoneSurrogate):
			return false, "", "", ErrPython
		case record == nil || len(record.Keys()) == 0: // Python's `not state`
			return true, "run " + on + " is gone", "", nil
		case !record.Truthy("lease_restarted"):
			return ended(on, record, now)
		}
		// stopped to wait on an older run's change, and started again: the wait goes on with
		// the new run, never round a loop Python would follow for good
		on = record.Str("lease_restarted")
		if on == "" || slices.Contains(seen, on) {
			return false, "", "", ErrPython
		}
	}
}

// ended is Run's answer for the run the wait reaches, its record read.
func ended(on string, record *run.Object, now time.Time) (bool, string, string, error) {
	if record.Str("state") == "stalled" {
		// going to the ladder, but nothing moves it except the seat: the wait is over
		return true, fmt.Sprintf("run %s stalled: resume it with ak run resume %s", on, on), "", nil
	}
	// a merge whose project has yet to prove itself live is still the seat's to wait on
	if live, err := Going(record, now); live || err != nil || seat.AwaitingLive(record, now) {
		return false, "", "", err
	}
	ended := "ended"
	for _, key := range []string{"state", "verdict"} { // Python's `verdict or state or "ended"`
		if record.Truthy(key) {
			ended = run.Text(record.Get(key))
		}
	}
	line := "run " + on + " ended " + ended
	if record.Truthy("merged") {
		line += ", merged"
	}
	return true, line, on, nil
}

// PR is wait_fact for a pull request: over once merged or closed, or, while open, once no run
// reviewing or landing it is going; an error saying why where gh cannot view it.
func PR(on string, now time.Time) (bool, string, error) {
	value, why, err := gh.JSON(run.Runs(), "pr", "view", on, "--json", "state,number,mergeCommit")
	if err != nil {
		return false, "", ErrPython
	}
	data, _ := value.(*run.Object)
	if data == nil || !slices.Contains([]string{"OPEN", "MERGED", "CLOSED"}, data.Str("state")) {
		return false, "", fmt.Errorf("gh cannot view %s: %s", on, cmp.Or(why, "GitHub did not answer"))
	}
	number := run.Text(data.Get("number"))
	switch data.Str("state") {
	case "MERGED":
		line := "PR #" + number + " merged"
		if commit := data.Dict("mergeCommit"); commit != nil && commit.Truthy("oid") {
			sha := []rune(run.Text(commit.Get("oid")))
			line += " as " + string(sha[:min(len(sha), 12)])
		}
		return true, line, nil
	case "CLOSED":
		return true, "PR #" + number + " closed without merging", nil
	}
	runs, err := run.OnPR(on)
	if err != nil {
		return false, "", ErrPython
	}
	// open, it waits while a wait on any going run reviewing or landing it would, and one such
	// run that would not (a stalled one) ends it with its own line
	first := ""
	for _, record := range runs {
		live, err := Going(record, now)
		if err != nil {
			return false, "", err
		}
		if !live {
			continue
		}
		over, why, _, err := Run(record.Str("run_id"), now)
		if err != nil || !over {
			return false, "", err
		}
		first = cmp.Or(first, why)
	}
	if first != "" {
		return true, first, nil
	}
	return true, fmt.Sprintf("PR #%s is open with no ak run going on it: ak run --review-pr %s --bg takes it", number, on), nil
}

// WorkLive is work_live as Go reads it: the line saying the seat's work is done and live once its
// plan is finished; a finished plan of a seat with runs of its own is Python's (`runs_owe`,
// `awaiting_live`).
func WorkLive(name string) (string, error) {
	finished, err := plan.Finished(name)
	if err != nil {
		return "", ErrPython
	}
	if !finished {
		return "", nil
	}
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) || record != nil && run.Seat(record) == name {
			return "", ErrPython
		}
	}
	return "your plan is done and its changes are live", nil
}

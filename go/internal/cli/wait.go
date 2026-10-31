package cli

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func init() { commands["wait"] = wait }

// wait is `ak wait PR_URL|RUN_ID`, as Python's watch.wait_main answers it: the seat ends its turn
// waiting on that pull request or run, written into its own record for the tick to end, and one
// already over is refused with its fact.  Python's are a wait reaching an exhausted run, one of a
// seat whose finished plan holds open deferred lines or who has runs of its own, and an ended
// run of the seat's own whose ending waits to be handed back, which Python prints and records.
func wait(args []string, out, errOut io.Writer) int {
	name, _, err := config.CurrentSession()
	if err != nil {
		fmt.Fprintf(errOut, "ak wait: %s\n", err)
		return 2
	}
	if name == "" {
		fmt.Fprintln(errOut, "ak wait: no seat: run it inside an orchestrator session")
		return 1
	}
	on := strings.TrimFunc(args[0], config.Space)
	kind, shown, fact := "pr", "", prFact
	if number := run.PRNumber(on); number != "" {
		shown = "PR #" + number
	} else if runID(on) && isDir(filepath.Join(run.Runs(), on)) {
		kind, shown, fact = "run", "run "+on, runFact
	} else {
		fmt.Fprintf(errOut, "ak wait: %s is neither a pull request URL nor a run id; ak waits on a pull request or a run, never on a session (ak run status lists runs)\n", commandhelp.Quote(on))
		return 1
	}
	now := time.Now()
	over, why, err := fact(on, now)
	switch {
	case err == nil && over && kind == "run" && owesHandBack(name, on):
		err = errLeft
	case err == nil && !over:
		why, err = workLive(name)
	}
	var own any
	if err == nil && why == "" && kind == "pr" {
		own, err = ownRun(name, on, now)
	}
	switch {
	case errors.Is(err, errLeft):
		return notImplemented(errOut, "wait")
	case err != nil:
		fmt.Fprintf(errOut, "ak wait: %s\n", err)
		return 1
	case why != "":
		fmt.Fprintf(errOut, "ak wait: %s; nothing is left to wait on\n", why)
		return 1
	}
	record := run.NewObject()
	record.Set("on", on)
	if own != nil {
		// its hand-back says the verdict and the merge; a wait on the pull request would be told
		// a second line whenever GitHub says merged before the run has saved it
		record.Set("on", own)
		kind, shown = "run", "run "+run.Text(own)+", on "+shown
	}
	record.Set("kind", kind)
	record.Set("at", seconds(now))
	if err := seat.Write(name, "wait", record); err != nil {
		fmt.Fprintf(errOut, "WARN could not record what %s is doing: %s\n", name, err)
		return 1
	}
	fmt.Fprintf(out, "%s: waiting on %s\n", name, shown)
	return 0
}

// going is transitions.going as Go reads it: an exhausted run's is Python's (`exhausted_wait`).
func going(record *run.Object, now time.Time) (bool, error) {
	if record.Str("state") == "exhausted" {
		return false, errLeft
	}
	return run.Going(record, now), nil
}

// runFact is wait_fact for a run: over, with the line saying how, once it is no longer going,
// or once the run its task was started again as is not.
func runFact(on string, now time.Time) (bool, string, error) {
	for seen := []string{on}; ; seen = append(seen, on) {
		record, err := run.Read(filepath.Join(run.Runs(), on))
		switch {
		case errors.Is(err, run.ErrLoneSurrogate):
			return false, "", errLeft
		case record == nil:
			return true, "run " + on + " is gone", nil
		case !record.Truthy("lease_restarted"):
			return endedFact(on, record, now)
		}
		// stopped to wait on an older run's change, and started again: the wait goes on with
		// the new run, never round a loop Python would follow for good
		on = record.Str("lease_restarted")
		if on == "" || slices.Contains(seen, on) {
			return false, "", errLeft
		}
	}
}

// endedFact is runFact's answer for the run the wait reaches, its record read.
func endedFact(on string, record *run.Object, now time.Time) (bool, string, error) {
	if record.Str("state") == "stalled" {
		// going to the ladder, but nothing moves it except the seat: the wait is over
		return true, fmt.Sprintf("run %s stalled: resume it with ak run resume %s", on, on), nil
	}
	if live, err := going(record, now); live || err != nil {
		return false, "", err
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
	return true, line, nil
}

// prFact is wait_fact for a pull request: over once merged or closed, or, while open, once no
// run reviewing or landing it is going; an error saying why where gh cannot view it.
func prFact(on string, now time.Time) (bool, string, error) {
	value, why, err := gh.JSON(run.Runs(), "pr", "view", on, "--json", "state,number,mergeCommit")
	if err != nil {
		return false, "", errLeft
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
		return false, "", errLeft
	}
	// open, it waits while a wait on any going run reviewing or landing it would, and one such
	// run that would not (a stalled one) ends it with its own line
	first := ""
	for _, record := range runs {
		live, err := going(record, now)
		if err != nil {
			return false, "", err
		}
		if !live {
			continue
		}
		over, why, err := runFact(record.Str("run_id"), now)
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

// workLive is work_live as Go reads it: the line saying the seat's work is done and live once its
// plan is finished; a finished plan of a seat with runs of its own is Python's (`runs_owe`,
// `awaiting_live`).
func workLive(name string) (string, error) {
	finished, err := plan.Finished(name)
	if err != nil {
		return "", errLeft
	}
	if !finished {
		return "", nil
	}
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) || record != nil && run.Seat(record) == name {
			return "", errLeft
		}
	}
	return "your plan is done and its changes are live", nil
}

// owesHandBack is whether the run is the seat's own and its ending waits to be handed back.
func owesHandBack(name, on string) bool {
	record, _ := run.Read(filepath.Join(run.Runs(), on))
	return record != nil && run.Seat(record) == name && record.Truthy("handback_pending")
}

// ownRun is the id of the seat's own going run reviewing or landing that pull request, nil for
// none.
func ownRun(name, on string, now time.Time) (any, error) {
	runs, err := run.OnPR(on)
	if err != nil {
		return nil, errLeft
	}
	for _, record := range runs {
		if run.Seat(record) != name {
			continue
		}
		if live, err := going(record, now); live || err != nil {
			return record.Get("run_id"), err
		}
	}
	return nil, nil
}

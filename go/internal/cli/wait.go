package cli

import (
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/waitfact"
)

func init() { commands["wait"] = wait }

// wait is `ak wait PR_URL|RUN_ID|JOB_ID`, as Python's watch.wait_main answers it: the seat ends its
// turn waiting on that pull request, run or job, written into its own record for the tick to end,
// and one already over is refused with its fact.  Python's are a wait of a seat whose finished plan holds
// open deferred lines or who has runs of its own.
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
	kind, shown, fact := "pr", "", waitfact.PR
	if number := run.PRNumber(on); number != "" {
		shown = "PR #" + number
	} else if runID(on) && isDir(filepath.Join(run.Runs(), on)) {
		kind, shown, fact = "run", "run "+on, runFact
	} else if runID(on) && isDir(filepath.Join(job.Jobs(), on)) {
		kind, shown, fact = "job", "job "+on, func(on string, _ time.Time) (bool, string, error) { return waitfact.Job(on) }
	} else {
		fmt.Fprintf(errOut, "ak wait: %s is neither a pull request URL nor a run id nor a job id; ak waits on a pull request, run or job, never on a session (ak run status lists them)\n", commandhelp.Quote(on))
		return 1
	}
	now := time.Now()
	over, why, err := fact(on, now)
	if err == nil && !over {
		why, err = waitfact.WorkLive(name)
	}
	var own any
	if err == nil && why == "" && kind == "pr" {
		own, err = ownRun(name, on, now)
	}
	if err == nil && over && kind == "run" && lookLeft(name, filepath.Join(run.Runs(), on)) {
		return notImplemented(errOut, "wait")
	}
	switch {
	case errors.Is(err, errLeft), errors.Is(err, waitfact.ErrPython):
		return notImplemented(errOut, "wait")
	case err != nil:
		fmt.Fprintf(errOut, "ak wait: %s\n", err)
		return 1
	case why != "":
		fmt.Fprintf(errOut, "ak wait: %s; nothing is left to wait on\n", why)
		if over && kind == "run" {
			waitEnding(name, on, errOut)
		}
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
	if err := seat.Write(name, "wait", record); errors.Is(err, run.ErrLoneSurrogate) {
		return notImplemented(errOut, "wait")
	} else if err != nil {
		fmt.Fprintf(errOut, "WARN could not record what %s is doing: %s\n", name, err)
		return 1
	}
	fmt.Fprintf(out, "%s: waiting on %s\n", name, shown)
	return 0
}

// runFact is waitfact.Run as `ak wait` reads it: the line, whatever run's ending that is.
func runFact(on string, now time.Time) (bool, string, error) {
	over, line, _, err := waitfact.Run(on, now)
	return over, line, err
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
		if run.Going(record, now) {
			return record.Get("run_id"), nil
		}
	}
	return nil, nil
}

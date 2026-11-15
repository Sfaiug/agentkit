package cli

import (
	"errors"
	"fmt"
	"io"
	"strconv"

	"agentkit/internal/job"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

func init() {
	commands["run stop"] = runStop
	commands["run resume"] = runResume
	commands["run merge"] = runMerge
}

// runStop is `ak run stop <id> [--keep]`, its arguments checked already: a job's stop or a run's
// Go leaves is Python's.
func runStop(args []string, out, errOut io.Writer) int {
	id := without(args, "--keep")[0]
	stop := loop.StopRun
	if isFile(job.ReceiptPath(id)) {
		stop = loop.StopJob
	}
	switch err := stop(id, contains(args, "--keep"), out); {
	case errors.Is(err, loop.ErrPython):
		return notImplemented(errOut, "run stop")
	case err != nil:
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 2
	}
	return 0
}

// runResume is `ak run resume <id> [--rounds N] [--bg]`, its arguments checked already: a job's
// in the background or with rounds, and any point Go cannot pick up from are Python's.
func runResume(args []string, out, errOut io.Writer) int {
	id, asked, ok := run.ResumeArgs(args)
	rounds, err := 0, error(nil)
	if asked != "" {
		rounds, err = strconv.Atoi(asked) // a number past Go's int is Python's
	}
	if !ok || err != nil || isFile(job.ReceiptPath(id)) && (contains(args, "--bg") || rounds > 0) {
		return notImplemented(errOut, "run resume")
	}
	if isFile(job.ReceiptPath(id)) {
		return resumeJob(id, out, errOut)
	}
	code, reason, err := launch.Resume(id, rounds, contains(args, "--bg"), out, errOut)
	switch {
	case errors.Is(err, launch.ErrPython):
		return notImplemented(errOut, "run resume")
	case err != nil:
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 2
	}
	if reason != "" {
		fmt.Fprintf(errOut, "ak run: %s\n", reason)
	}
	return code
}

// resumeJob is `ak run resume <job>` in the foreground.
func resumeJob(id string, out, errOut io.Writer) int {
	code, err := launch.ResumeJob(id, out)
	switch {
	case errors.Is(err, launch.ErrPython):
		return notImplemented(errOut, "run resume")
	case err != nil:
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 2
	}
	return code
}

// runMerge is `ak run merge <id>`, its arguments and its record's refusals checked already: a run
// or host Go does not deliver on is Python's.
func runMerge(args []string, out, errOut io.Writer) int {
	code, reason, err := launch.Merge(args[0], out, errOut)
	switch {
	case errors.Is(err, launch.ErrPython):
		return notImplemented(errOut, "run merge")
	case err != nil:
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 2
	}
	if reason != "" {
		fmt.Fprintf(errOut, "ak run: %s\n", reason)
	}
	return code
}

package cli

import (
	"errors"
	"fmt"
	"io"
	"strconv"

	"agentkit/internal/job"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
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
	id := without(args, "--bg")
	rounds := 0
	if len(id) == 3 {
		// `<id> --rounds N`; a number past Go's int is Python's
		var err error
		if rounds, err = strconv.Atoi(id[2]); err != nil {
			return notImplemented(errOut, "run resume")
		}
		id = id[:1]
	}
	if len(id) != 1 || isFile(job.ReceiptPath(id[0])) && (contains(args, "--bg") || rounds > 0) {
		return notImplemented(errOut, "run resume")
	}
	if isFile(job.ReceiptPath(id[0])) {
		return resumeJob(id[0], out, errOut)
	}
	code, reason, err := launch.Resume(id[0], rounds, contains(args, "--bg"), out, errOut)
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

package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/box"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/job"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

const runFlagsUsage = "ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N] | ak run --review-pr <url> [--review MODEL] [--first] [--bg]"
const runUsage = "usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N] | ak run --review-pr <url> | ak run status [<runid>] | ak run resume <runid> | ak run stop <runid> [--keep] | ak run clean <runid> | ak run gc"

func init() {
	commands["run"] = launchRun
	commands["run clean"] = runClean
}

// runClean is `ak run clean <id>`, its arguments checked already: a refusal in Python's words.
func runClean(args []string, out, errOut io.Writer) int {
	if err := loop.Clean(args[0], out); err != nil {
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 2
	}
	return 0
}

// launchRun is `ak run <task.md>` or `ak run --review-pr <url>` where Go makes the launch: one
// preflight refuses, recorded as a run in error, or a run preflight passes, which it follows unless
// told --bg.  Any other launch
// it leaves to Python before it writes anything.  `--drive` is that run's own process, and
// `--lander` a landing line's.
func launchRun(args []string, out, errOut io.Writer) int {
	if len(args) == 2 && args[0] == loop.DriveFlag {
		return loop.Drive(args[1])
	}
	if len(args) == 2 && args[0] == "--lander" {
		return loop.CheckLine(args[1], out)
	}
	parsed, problem := parse(args, launch.Values, launch.Switches, runFlagsUsage)
	var code int
	var reason string
	var err error
	switch url := parsed.values["--review-pr"]; {
	case runSubcommand(args) || problem != "":
		return notImplemented(errOut, "run")
	case url != "":
		code, reason, err = launch.Review(url, parsed.values, parsed.flags, out, errOut)
	case len(parsed.words) == 1:
		code, reason, err = launch.Task(config.Absolute(parsed.words[0]), parsed.values, parsed.flags, out, errOut)
	default:
		return notImplemented(errOut, "run")
	}
	switch {
	case errors.Is(err, launch.ErrPython):
		return notImplemented(errOut, "run")
	case errors.Is(err, launch.ErrStopped):
		return 1
	case err != nil:
		fmt.Fprintf(errOut, "ak run: %v\n", err)
		return 1
	}
	if reason != "" {
		fmt.Fprintf(errOut, "ak run: %s\n", reason)
	}
	return code
}

func runSubcommand(args []string) bool {
	return len(args) > 0 && contains([]string{"--lander", loop.DriveFlag, "status", "show", "clean", "gc", "resume", "merge", "stop"}, args[0])
}

func validateRun(args []string) string {
	if runSubcommand(args) {
		return validateRunSubcommand(args[0], args[1:])
	}
	parsed, problem := parse(args, launch.Values, launch.Switches, runFlagsUsage)
	if problem != "" {
		return problem
	}
	if why := launch.SeatRefusal(parsed.values, parsed.flags); why != "" {
		return why
	}
	if url := parsed.values["--review-pr"]; url != "" {
		_, parallel := parsed.values["--parallel"]
		if len(parsed.words) > 0 || parsed.values["--rounds"] != "" || parsed.values["--exec"] != "" || parsed.flags["--no-worktree"] || parallel {
			return "usage: ak run --review-pr <url> [--review MODEL] [--first] [--bg]: no task file, no executor, no rounds"
		}
		if !gh.PullURL.MatchString(url) {
			return fmt.Sprintf("--review-pr needs a GitHub PR URL (got %s)", commandhelp.Quote(url))
		}
	} else if len(parsed.words) == 0 {
		return runUsage
	}
	for _, flag := range []string{"--rounds", "--parallel"} {
		if value, ok := parsed.values[flag]; ok && !positive(value) {
			return fmt.Sprintf("%s must be a positive integer (got %s)", flag, commandhelp.Quote(value))
		}
		// every task's numbers are read before `--parallel` is judged, `--rounds` given or not, as
		// Python's main reads them, except by a queued launch's own child
		for _, word := range parsed.words {
			if flag != "--rounds" || launch.Queued() {
				break
			}
			budget, err := launch.Budget(config.Absolute(word))
			if problem := launch.RoundsRefusal(parsed.values["--rounds"], budget, err); problem != "" {
				return problem
			}
		}
	}
	if err := box.Check(); err != nil {
		return err.Error()
	}
	if err := config.Check(); err != nil {
		return err.Error()
	}
	if _, _, err := config.RunMemoryMaxMB(); err != nil {
		return err.Error()
	}
	if _, parallel := parsed.values["--parallel"]; parallel && len(parsed.words) == 1 {
		return "usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg]: --parallel needs more than one task file"
	}
	// Every task is read before any is judged whole, so a job names the first file it cannot
	// read before a sentence about another; a job's sentence names its file.
	type read struct {
		path string
		meta map[string]string
		cmds []string
	}
	var tasks []read
	for _, word := range parsed.words {
		path := config.Absolute(word)
		if !isFile(path) {
			return "no such task file: " + path
		}
		meta, cmds, err := task.Read(path)
		if err != nil {
			return err.Error()
		}
		tasks = append(tasks, read{path, meta, cmds})
	}
	for _, each := range tasks {
		refusal, err := launch.Refusal(each.path, each.meta, each.cmds)
		if err != nil {
			return err.Error()
		}
		if refusal != "" {
			if len(tasks) > 1 {
				return each.path + ": " + refusal
			}
			return refusal
		}
	}
	return ""
}

func validateRunSubcommand(verb string, args []string) string {
	if verb == "--lander" {
		if len(args) != 1 || filepath.Base(args[0]) != args[0] || !strings.HasPrefix(args[0], ".merge-") {
			return "usage: ak run --lander LINE"
		}
		return ""
	}
	if verb == loop.DriveFlag {
		if len(args) != 1 {
			return runUsage
		}
		return ""
	}
	if verb == "gc" {
		if len(args) > 0 && !(len(args) == 1 && args[0] == "--dry-run") {
			return commandhelp.Usage("run gc")
		}
		return ""
	}
	usage := "usage: ak run " + verb + " <runid>"
	asked := ""
	switch verb {
	case "status", "show":
		if contains(args, "--tests") {
			if len(args) > 1 {
				return "usage: ak run status --tests"
			}
			return ""
		}
		usage = commandhelp.Usage("run status") + " [--pending]"
		args = without(args, "--history", "--json", "--plain", "--why", "--pending")
		if len(args) > 1 || (len(args) == 1 && strings.HasPrefix(args[0], "-")) {
			return usage
		}
		if len(args) == 0 {
			return ""
		}
	case "stop":
		usage = commandhelp.Usage("run stop")
		args = without(args, "--keep")
	case "resume":
		usage += " [--rounds N] [--bg]"
		args = without(args, "--bg")
		if len(args) == 3 && args[1] == "--rounds" && positive(args[2]) {
			asked = args[2]
			args = args[:1]
		}
	}
	if len(args) != 1 || (verb != "status" && verb != "show" && !runID(args[0])) {
		return usage
	}
	if asked != "" {
		budget, err := launch.ResumeBudget(args[0])
		if problem := launch.RoundsRefusal(asked, budget, err); problem != "" {
			return problem
		}
	}
	runs := filepath.Join(config.Home(), "runs")
	if verb == "resume" && isFile(job.ReceiptPath(args[0])) {
		return "" // a job's, which Python resumes (runResume)
	}
	if !runID(args[0]) {
		return fmt.Sprintf("no such run: %s (looked in %s)", args[0], runs)
	}
	if verb == "status" || verb == "show" {
		if !jobNamed(args[0]) && !isDir(filepath.Join(runs, args[0])) {
			return fmt.Sprintf("no such run: %s (looked in %s)", args[0], runs)
		}
		return ""
	}
	if verb == "merge" {
		return loop.MergeRefused(args[0])
	}
	if _, err := os.ReadFile(filepath.Join(runs, args[0], "run.json")); err != nil {
		if verb == "stop" && isFile(job.ReceiptPath(args[0])) {
			return ""
		}
		if verb == "resume" {
			return fmt.Sprintf("no resumable run: %s (looked in %s)", args[0], runs)
		}
		return fmt.Sprintf("no such run: %s (looked in %s)", args[0], runs)
	}
	return ""
}

// jobNamed is whether the id names a job with tasks, which `ak run status` shows over a run,
// or may: Python reads a receipt holding a lone surrogate, which Go cannot.
func jobNamed(id string) bool {
	receipt, err := run.ReadJSON(job.ReceiptPath(id))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return true
	}
	if receipt == nil {
		return false
	}
	_, ok := receipt.Get("tasks").([]any)
	return ok
}

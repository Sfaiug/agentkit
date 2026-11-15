package launch

import (
	"errors"
	"io/fs"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// RoundsRefusal is why `--rounds asked` is refused, "" for none or with none asked: Python's
// rounds_refusal against the budget in force, which `ak run` reads with Budget and `ak run resume`
// with ResumeBudget.  A read that fails says why in its error's words, rounds asked or not; a
// budget Python reads (ErrPython) Python judges, as the command is handed over.
func RoundsRefusal(asked string, budget int, err error) string {
	switch {
	case errors.Is(err, ErrPython):
		return ""
	case err != nil:
		return err.Error()
	}
	return task.RoundsOver(asked, "--rounds", budget)
}

// ResumeArgs are the run and the rounds `ak run resume` is given, Python's run.resume_args:
// `<id> [--rounds N] [--bg]`, its rounds "" where none are asked, false where they are not that.
func ResumeArgs(args []string) (id, rounds string, ok bool) {
	args = slices.DeleteFunc(slices.Clone(args), func(arg string) bool { return arg == "--bg" })
	if len(args) == 3 && args[1] == "--rounds" && config.Digits(args[2]) && strings.TrimLeft(args[2], "0") != "" {
		rounds, args = args[2], args[:1]
	}
	if len(args) != 1 || filepath.Base(args[0]) != args[0] || args[0] == "." || args[0] == ".." {
		return "", "", false
	}
	return args[0], rounds, true
}

// ResumeBudget is the rounds a resume of id holds to, as Python's resume reads them: a job's,
// those in force for the checkout it was launched from (config.policy(job["cwd"])); a run's, those
// its record kept, the host's with no record (run.Policy).  ErrPython for a receipt Python resumes
// as no job.
func ResumeBudget(id string) (int, error) {
	var numbers config.Numbers
	receipt, err := run.ReadJSON(job.ReceiptPath(id))
	switch {
	case errors.Is(err, fs.ErrNotExist):
		held, _ := run.Read(filepath.Join(run.Runs(), id))
		if held == nil { // missing, unreadable or no object
			held = run.Fields()
		}
		numbers, err = run.Policy(held)
	case err != nil || receipt == nil:
		return 0, ErrPython
	default:
		if _, listed := receipt.Get("tasks").([]any); !listed {
			return 0, ErrPython
		}
		numbers, err = checkoutNumbers(receipt.Str("cwd"))
	}
	return numbers.Rounds, err
}

// checkoutNumbers is the numbers in force for a checkout, Python's config.policy: run.LaunchPolicy's,
// but the host's where it has fetched no default branch, which origin is not asked for.
func checkoutNumbers(checkout string) (config.Numbers, error) {
	if gitcall.FetchedRulesTip(checkout) == "" {
		return config.HostNumbers()
	}
	return run.LaunchPolicy(checkout)
}

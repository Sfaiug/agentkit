package launch

import (
	"cmp"
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// ladder is the task's word on its run's ending, and what else the task keeps, as Python's
// job_ladder settles a run it takes no further: merged, passed, stopped, blocked, or failed and
// needing you, for an exhausted run that waits for no budget, a FAIL its reviews failed, one
// neither at its round budget nor short of rounds, or one with no other of the run's workers to
// rerun it on.  "" where the ladder's next step is Python's: a wait for budget or a login, a run
// parked waiting or not ended, a PASS still to deliver, or the one rerun on the next executor.
func ladder(task, record *run.Object, workers []string) (string, []any) {
	name, state, word := task.Str("name"), record.Str("state"), classify(record)
	why := cmp.Or(record.Str("error"), "no reason was recorded")
	// an exhausted run that is really a spent round budget, which only more rounds fix
	// (job_round_shortfall)
	short := state == "exhausted" && (record.Truthy("review_pending") || strings.Contains(why, "round budget"))
	switch {
	case state == "exhausted" && slices.ContainsFunc([]string{"100% used", "no eligible reviewer",
		"API/transport errors", "gave no verdict twice"}, func(said string) bool { return strings.Contains(why, said) }):
		return "", nil // a wait for budget (job_budget_exhausted, job_transport_exhausted)
	case state == "exhausted" && !short:
		// a stopped tool or a structural complaint, which no resume fixes
		said := []rune(why)
		return "failed", []any{"verdict_line", fmt.Sprintf("%s: FAIL: needs you (%s)", name, string(said[:min(len(said), 300)])),
			"findings", why}
	case state != "exhausted" && !run.Ended(record):
		return "", nil // parked waiting, on a login, or still going
	case word == "merged" || word == "passed" || word == "stopped":
		return word, []any{"verdict_line", verdictLine(name, word, record)}
	case state == "pass" && record.Truthy("merge_failed"):
		return "", nil // finished with `ak run merge`
	case word == "failed" && (run.AtBudget(record) || short) && !handback.ReviewFailed(record) &&
		slices.ContainsFunc(workers, func(worker string) bool { return worker != task.Str("executor") }):
		return "", nil // the one rerun, on the next executor (job_next_executor)
	}
	return word, []any{"verdict_line", verdictLine(name, word, record),
		"findings", cmp.Or(record.Str("findings"), record.Str("error"))}
}

// end settles the task on its word, finished now, with what else it keeps, and says its line, as
// Python's ladder and run_job_loop settle one.
func (j *jobRun) end(task *run.Object, word string, kept ...any) error {
	run.SetAll(task, append([]any{"state", word, "finished_at", run.Float(seconds())}, kept...)...)
	if err := job.Save(j.dir, j.receipt); err != nil {
		return err
	}
	j.say(task.Str("verdict_line"))
	return nil
}

// verdictLine is the line of a task its run settled on that word, Python's job_verdict_line for a
// task no rerun went on: a delivered one's rounds, and the pull request a merge went through.
func verdictLine(name, word string, record *run.Object) string {
	rounds := len(record.List("round_summaries"))
	switch word {
	case "stopped":
		return name + ": stopped"
	case "blocked":
		return name + ": BLOCKED: " + cmp.Or(config.Fold(record.Str("error")), "the task cannot be completed as written")
	case "merged", "passed":
		tail := ""
		if pr := run.Text(record.Get("pr")); word == "merged" && record.Truthy("pr") && strings.HasPrefix(pr, "http") {
			tail = " " + pr
		}
		line := fmt.Sprintf("%s: PASS, %s after %d rounds%s", name, word, rounds, tail)
		return strings.ReplaceAll(line, " after 0 rounds", "")
	}
	return fmt.Sprintf("%s: FAIL after %d rounds: needs you", name, max(rounds, 1))
}

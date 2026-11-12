package job

import (
	"cmp"
	"fmt"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Classify is a finished run's word for its task, Python's job_classify: merged, passed where no
// merge was asked, the task is scratch, or its target already had the work or is none, else
// stopped, blocked or failed.
func Classify(record *run.Object, models map[string]config.Model) string {
	switch state := record.Str("state"); {
	case state == "stopped" || state == "blocked":
		return state
	case state == "not_needed":
		return "passed"
	case record.Truthy("merged"):
		return "merged"
	case !run.ReviewPass(record, models):
		return "failed"
	case record.Truthy("no_merge") || record.Truthy("scratch") || record.Truthy("on_target"),
		record.Truthy("target") && strings.ToLower(run.Text(record.Get("target"))) == "none":
		return "passed"
	}
	return "failed"
}

// VerdictLine is the task's line for the word Classify gave its run, Python's job_verdict_line:
// what blocked it, the rounds a pass took and the pull request a merge went through, or the
// rounds a failure took and what was tried before it needed its owner.
func VerdictLine(task *run.Object, word string, record *run.Object) string {
	name := run.Text(task.Get("name"))
	switch word {
	case "stopped":
		return name + ": stopped"
	case "blocked":
		why := config.Fold(cmp.Or(record.Str("error"), task.Str("findings")))
		return name + ": BLOCKED: " + cmp.Or(why, "the task cannot be completed as written")
	case "merged", "passed":
		tail := ""
		if pr := run.Text(record.Get("pr")); word == "merged" && record.Truthy("pr") && strings.HasPrefix(pr, "http") {
			tail = " " + pr
		}
		line := fmt.Sprintf("%s: PASS, %s after %d rounds%s", name, word, len(record.List("round_summaries")), tail)
		return strings.ReplaceAll(line, " after 0 rounds", "")
	}
	tried := ""
	if task.Truthy("resume_attempted") {
		tried += ", resumed once"
	}
	if task.Truthy("rerun_executor") {
		tried += ", rerun on " + run.Text(task.Get("rerun_executor"))
	}
	if tried != "" {
		tried += ", still failing"
	}
	// a failure that recorded no round still took one
	return fmt.Sprintf("%s: FAIL after %d rounds%s: needs you", name, max(1, len(record.List("round_summaries"))), tried)
}

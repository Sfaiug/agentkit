package handback

import (
	"cmp"
	"fmt"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// ResultNames is the move of an ending whose result names the fix to launch.
const ResultNames = "launch the fix the result names"

// Decision is the ending's word, reason and next move, shared by its result and hand-back.
// An empty move leaves nothing to decide. Detail is dropped first when a typed line needs room.
func Decision(record *run.Object, dir, delivery string) (word, why, move, detail string) {
	state := record.Str("state")
	review := &handin.Review{}
	for _, row := range record.List("review_records") {
		if row, ok := row.(*run.Object); ok {
			review.Records = append(review.Records, row)
		}
	}
	word = "FAIL"
	switch {
	case state == "not_needed":
		word = "DONE"
	case state == "blocked" || state == "error":
		word = strings.ToUpper(state)
	case strings.HasPrefix(delivery, "PASS"):
		word = "NOT MERGED"
		if record.Truthy("merged") {
			word = "PASS merged"
		} else if record.Truthy("scratch") {
			word = "PASS delivered"
		}
	}
	switch {
	case state == "not_needed":
		why = config.Fold(delivery)
	case state == "blocked" || state == "error":
		why = config.Fold(cmp.Or(record.Str("error"), "no reason was recorded"))
	case strings.HasPrefix(record.Str("error"), "killed: memory cap"):
		why = config.Fold(record.Str("error"))
	case !run.Ended(record) && run.NeedsRecovery(record):
		why = strings.TrimRight(config.Fold(run.RecoveryReason(record)), ".")
	case strings.HasPrefix(delivery, "PASS, not merged: "):
		why = strings.TrimPrefix(delivery, "PASS, not merged: ")
	case strings.HasPrefix(delivery, "PASS"):
		why = cmp.Or(record.Str("pr"), strings.TrimPrefix(delivery, "PASS, "))
	case review.Verdict() == "FAIL" && len(review.Of("finding")) > 0:
		row := review.Of("finding")[0]
		why = fmt.Sprintf("%s:%s - %s", row.Str("path"), run.Text(row.Get("line")), row.Str("what"))
	default:
		var reasons []string
		if judged := record.Dict("review"); judged != nil && judged.Truthy("overridden") {
			reasons = append(reasons, judged.Str("overridden"))
		}
		if check := FailedCheck(record); check != "" {
			reasons = append(reasons, check)
		}
		why = strings.TrimRight(cmp.Or(strings.Join(reasons, "; "), config.Fold(cmp.Or(record.Str("merge_note"),
			record.Str("error"), "no reason was recorded"))), ".")
	}
	if strings.HasPrefix(word, "PASS") || word == "DONE" || record.Truthy("merged") ||
		state == "waiting" || state == "stopped" || state != "exhausted" && run.Going(record, time.Now()) {
		return
	}
	move = "read the result"
	provider := run.ExhaustedWait(record) != ""
	named := cmp.Or(strings.TrimPrefix(run.ContinueLine(record, dir, time.Now()), "continue: "), RetryCommand(record))
	switch {
	case provider:
		move = "wait for the provider"
	case named != "":
		move, detail = ResultNames, ", `"+named+"`"
	case state == "fail" && review.Verdict() == "FAIL" && run.FirstNumber(record, "rounds") > 0 &&
		float64(len(record.List("round_summaries"))) >= run.FirstNumber(record, "rounds"):
		move = "split the task"
	case state == "blocked" || FailedCheck(record) != "":
		move = "rewrite the task and relaunch it"
		if record.Truthy("branch") {
			detail = " with `from: " + record.Str("branch") + "`"
		}
	}
	return
}

// RetryCommand finishes a PASS whose delivery failed, Python's retry_command.
func RetryCommand(record *run.Object) string {
	if record.Str("state") != "pass" || !record.Truthy("merge_failed") || record.Truthy("scratch") ||
		record.Truthy("review_pr") || !record.Truthy("repo") {
		return ""
	}
	return "ak run merge " + record.Str("run_id")
}

// FailedCheck names the final or per-round check still failing, Python's failed_check.
func FailedCheck(record *run.Object) string {
	first := func(gate string) string {
		if history := record.Dict("done_when_failure"); history != nil {
			if rows := history.List(gate); len(rows) > 0 {
				if pair, ok := rows[0].([]any); ok && len(pair) == 2 {
					line := "`" + run.Text(pair[0]) + "`"
					if run.Text(pair[1]) != "" {
						line += " — " + run.Text(pair[1])
					}
					return line
				}
			}
		}
		return ""
	}
	if final := record.Dict("final_check"); final != nil && final.Str("outcome") == "failed" {
		where, log := "", "see final-check.log"
		switch final.Str("where") {
		case "round":
			where, log = " in round", "see once.log"
			if final.Truthy("round") {
				rnd := run.Text(final.Get("round"))
				where, log = where+" "+rnd, "see round-"+rnd+"/once.log"
			}
		case "landing":
			where = " at landing"
		}
		return "the final check failed" + where + ": " + cmp.Or(final.Str("line"), first("once"), log)
	}
	if line := first("every"); line != "" {
		return "the done-when failed: " + line
	}
	return ""
}

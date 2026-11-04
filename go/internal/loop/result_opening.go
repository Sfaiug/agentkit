package loop

import (
	"bufio"
	"cmp"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// resultOpening is the decision in full, or today's delivery heading when nothing needs deciding.
func resultOpening(dir string, record *run.Object, outcome string) string {
	state := record.Str("state")
	provider := state == "exhausted" && !record.Truthy("replaced") &&
		(record.Truthy("quota_dry") || strings.Contains(record.Str("error"), "API/transport errors"))
	if record.Truthy("merged") {
		if saved := handin.Answer(filepath.Join(dir, "result.md")); strings.HasPrefix(saved, "# NOT LIVE ") {
			opening, _, _ := strings.Cut(saved, "\n\n")
			return opening
		}
	}
	if record.Truthy("merged") || state == "not_needed" || state == "stopped" || state == "waiting" ||
		strings.HasPrefix(outcome, "PASS") && record.Truthy("scratch") ||
		state != "exhausted" && run.Going(record, time.Now()) {
		return "# " + outcome + " — " + cmp.Or(record.Str("title"), filepath.Base(dir))
	}
	word, why, move := "FAIL", "", "read the result"
	if strings.HasPrefix(outcome, "PASS, not merged: ") {
		word, why = "NOT MERGED", strings.TrimPrefix(outcome, "PASS, not merged: ")
	}
	if state == "blocked" || state == "error" {
		word = strings.ToUpper(state)
		why = cmp.Or(record.Str("error"), "no reason was recorded")
	} else if strings.HasPrefix(record.Str("error"), "killed: memory cap") {
		why = record.Str("error")
	} else if !run.Ended(record) && run.NeedsRecovery(record) {
		why = strings.TrimRight(run.RecoveryReason(record), ".")
	}
	review := &handin.Review{}
	for _, each := range record.List("review_records") {
		if row, ok := each.(*run.Object); ok {
			review.Records = append(review.Records, row)
		}
	}
	claims := review.Of("finding")
	final, history := record.Dict("final_check"), record.Dict("done_when_failure")
	if final == nil {
		final = run.NewObject()
	}
	if history == nil {
		history = run.NewObject()
	}
	overridden := ""
	if judged := record.Dict("review"); judged != nil {
		overridden = judged.Str("overridden")
	}
	check := failedCheck(record)
	if final.Str("outcome") == "failed" {
		check = "the final check failed"
		if where := final.Str("where"); where != "" {
			check += " at " + where
		}
		check += ": " + cmp.Or(final.Str("line"), "see final-check.log")
	}
	if why == "" {
		if len(claims) > 0 && review.Verdict() == "FAIL" {
			why = handin.ItemText(claims[0])
		} else {
			why = strings.TrimRight(cmp.Or(overridden, check,
				record.Str("merge_note"), record.Str("error"), "no reason was recorded"), ".")
		}
	}
	parts := []string{why}
	for _, row := range claims {
		if text := handin.ItemText(row); !slices.Contains(parts, text) {
			parts = append(parts, text)
		}
	}
	if check != "" && !slices.Contains(parts, check) {
		parts = append(parts, check)
	}
	every, latest := filepath.Join(dir, "donewhen.log"), 0
	logs, _ := filepath.Glob(filepath.Join(dir, "round-*", "donewhen.log"))
	for _, path := range logs {
		if n, _ := strconv.Atoi(strings.TrimPrefix(filepath.Base(filepath.Dir(path)), "round-")); n > latest {
			every, latest = path, n
		}
	}
	for _, gate := range [][2]string{{"every", every}, {"once", cmp.Or(final.Str("log"), filepath.Join(dir, "final-check.log"))}} {
		failed := history.List(gate[0])
		if len(failed) == 0 && !(gate[0] == "once" && final.Str("outcome") == "failed") {
			continue
		}
		text := handin.Answer(gate[1])
		if checks := failingChecks(text); len(checks) > 0 {
			failed = checks
		}
		var records []string
		for _, block := range strings.Split(text, "\n\n") {
			if checkRecord.MatchString(block) {
				records = append(records, block)
			} else if len(records) > 0 {
				records[len(records)-1] += "\n\n" + block
			}
		}
		for _, each := range failed {
			pair, ok := each.([]any)
			if !ok || len(pair) != 2 {
				continue
			}
			output := ""
			for len(records) > 0 {
				block := records[0]
				records = records[1:]
				mark := checkRecord.FindStringSubmatch(block)
				if mark[1] == run.Text(pair[0]) && mark[2] != "exit 0" {
					output = block[len(mark[0]):]
					break
				}
			}
			where := filepath.Dir(gate[1])
			if gate[0] == "every" {
				where = dir
			}
			parts = append(parts, checkLine([]any{pair[0], cmp.Or(firstDiagnostics(output, where), run.Text(pair[1]))}))
		}
	}
	if named := strings.TrimPrefix(run.ContinueLine(record, dir, time.Now()), "continue: "); named != "" {
		move = "launch the fix the result names, `" + named + "`"
	} else if state == "pass" && record.Truthy("merge_failed") && !record.Truthy("scratch") &&
		!record.Truthy("review_pr") && record.Truthy("repo") {
		move = "launch the fix the result names, `ak run merge " + record.Str("run_id") + "`"
	} else if state == "fail" && review.Verdict() == "FAIL" &&
		float64(len(record.List("round_summaries"))) >= run.FirstNumber(record, "rounds") && run.FirstNumber(record, "rounds") > 0 {
		move = "split the task"
	} else if state == "blocked" || check != "" {
		move = "rewrite the task and relaunch it"
		if record.Truthy("branch") {
			move += " with `from: " + record.Str("branch") + "`"
		}
	}
	if provider {
		move = "wait for the provider"
	}
	return run.Decision(record, dir, word, strings.Join(parts, "; "), move, true)
}

// firstDiagnostics follows only a regular kept output in the runner's protected directory.
func firstDiagnostics(text, where string) string {
	where = config.Resolve(where)
	var shown []string
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		path, named := strings.CutPrefix(line, "[only part of this output is shown; all of it is in ")
		path, ended := strings.CutSuffix(path, "]")
		match, _ := filepath.Match("*-whole-*.log", filepath.Base(path))
		if named && ended && match && filepath.Dir(path) == where && path == filepath.Clean(path) {
			if file := diagnosticFile(path); file != nil {
				reader := bufio.NewReader(file)
				for len(shown) < 3 {
					part, err := reader.ReadString('\n')
					if part = strings.TrimSpace(part); part != "" {
						shown = append(shown, part)
					}
					if err != nil {
						break
					}
				}
				file.Close()
				if len(shown) == 3 {
					break
				}
				continue
			}
		}
		shown = append(shown, line)
		if len(shown) == 3 {
			break
		}
	}
	return strings.Join(shown, " ")
}

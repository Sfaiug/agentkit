package loop

import (
	"bufio"
	"cmp"
	"fmt"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// resultOpening is the decision in full, or today's delivery heading when nothing needs deciding.
func resultOpening(dir string, record *run.Object, outcome string) string {
	if record.Truthy("merged") {
		if saved := handin.Answer(filepath.Join(dir, "result.md")); strings.HasPrefix(saved, "# NOT LIVE ") {
			opening, _, _ := strings.Cut(saved, "\n\n")
			return opening
		}
	}
	word, why, move, detail := handback.Decision(record, dir, outcome)
	if move == "" {
		return "# " + outcome + " — " + cmp.Or(record.Str("title"), filepath.Base(dir))
	}
	return decisionReport(dir, record, word, why, move+detail)
}

// decisionReport is a decision's opening in full, Python's decision(report=True): why with every
// blocking claim and failing check, and their first diagnostics.
func decisionReport(dir string, record *run.Object, word, why, move string) string {
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
	parts := []string{why}
	for _, row := range claims {
		if why == fmt.Sprintf("%s:%s - %s", row.Str("path"), run.Text(row.Get("line")), row.Str("what")) {
			parts[0] = handin.ItemText(row)
		}
		if text := handin.ItemText(row); !slices.Contains(parts, text) {
			parts = append(parts, text)
		}
	}
	if check := handback.FailedCheck(record); check != "" && !slices.Contains(parts, check) {
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

package handback

import (
	"fmt"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// Finished task runs use the same delivery outcome their result shows. A line whose full
// reason does not fit still waits for Python's sentence shortening and saved notice.
func finishedLine(record *run.Object, dir string) string {
	word, why := "", ""
	delivery := run.Delivery(record, run.Models())
	switch {
	case record.Str("state") == "not_needed":
		word, why = "DONE", delivery
	case record.Str("state") == "pass" && strings.HasPrefix(delivery, "PASS"):
		word, why = "NOT MERGED", strings.TrimPrefix(delivery, "PASS, not merged: ")
		if record.Truthy("merged") {
			word, why = "PASS merged", record.Str("pr")
		} else if record.Truthy("scratch") {
			word, why = "PASS delivered", "delivered"
		}
	case record.Str("state") == "fail":
		review := &handin.Review{}
		for _, row := range record.List("review_records") {
			if row, ok := row.(*run.Object); ok {
				review.Records = append(review.Records, row)
			}
		}
		rows := review.Of("finding")
		if len(rows) == 0 {
			return ""
		}
		row := rows[0]
		why = fmt.Sprintf("%s:%s - %s", row.Str("path"), run.Text(row.Get("line")), row.Str("what"))
		rounds, _ := record.Int("rounds")
		if len(record.List("round_summaries")) < rounds || rounds == 0 {
			return ""
		}
		line := run.Decision(record, dir, "FAIL", why, "split the task", false)
		if utf8.RuneCountInString(line) <= min(decisionMost, longest()) && len(line) <= typedMostByte {
			return line
		}
		return ""
	default:
		return ""
	}
	line := fmt.Sprintf("run %s finished %s: %s. Result: %s. Decide the next step.", filepath.Base(dir), word, config.Fold(why), filepath.Join(dir, "result.md"))
	if utf8.RuneCountInString(line) <= longest() && len(line) <= typedMostByte {
		return line
	}
	return ""
}

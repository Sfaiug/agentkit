package run

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Decision renders the seat's decision, as a line or an uncut result.md opening with report.
// The caller of a typed line enforces its composer bound.
func Decision(record *Object, dir, word, why, move string, report bool) string {
	rounds := "0"
	if record.Truthy("rounds") {
		rounds = Text(record.Get("rounds"))
	}
	spent := fmt.Sprintf("(%d of %s)", len(record.List("round_summaries")), rounds)
	if ReviewOff(record) {
		spent = "(no review)"
	}
	why = strings.Join(strings.Fields(why), " ")
	if why == "" {
		why = "no reason was recorded"
	}
	if report {
		title := record.Str("title")
		if title == "" {
			title = filepath.Base(dir)
		}
		return fmt.Sprintf("# %s %s — %s\nWhy: %s\nNext: %s", word, spent, title, why, move)
	}
	if !strings.HasSuffix(why, ".") && !strings.HasSuffix(why, "!") && !strings.HasSuffix(why, "?") {
		why += "."
	}
	result := filepath.Join(dir, "result.md")
	home, err := os.UserHomeDir()
	if rest, err2 := filepath.Rel(home, result); err == nil && err2 == nil && rest != ".." && !strings.HasPrefix(rest, "../") {
		result = "~/" + rest
	}
	return fmt.Sprintf("run %s %s %s: %s Next: %s. Result: %s", filepath.Base(dir), word, spent, why, move, result)
}

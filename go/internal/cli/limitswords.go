package cli

import (
	"fmt"
	"strings"

	"agentkit/internal/config"
)

// limitNames is each of config's numbers on `Limits`, Python's LIMIT_NAMES: its name on the page,
// how `Limits`' value on `c` says it, before the number and its unit after, the steps ← and →
// move it through (limitStep), and what its row says while it is off.  Owner, 3 Nov 2026: the
// keys' own names were unclear to users; 5 Nov 2026: "The executor cap moves in steps of 100, the
// orchestrator's in steps of 25."
var limitNames = map[string]struct {
	name, short, unit string
	steps             []any
	off               string
}{
	"review_rounds": {"Review rounds", "review", "rounds", []any{0, 1, 2, 3, 4, 5},
		"A change lands on its checks; no reviewer."},
	"executor_lines": {"Max lines per executor task", "executor", "lines",
		[]any{0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, "no limit"}, config.ExecutorsOff},
	"orchestrator_lines": {"Max lines per orchestrator task", "orchestrator", "lines",
		[]any{0, 25, 50, 75, 100, 125, 150, 175, 200, "no limit"}, "The orchestrator builds nothing; executors build every change."},
}

// limitsSaid is `Limits`' value on `c`, Python's menu.limits_value: each number in force under its
// short name, `off` for zero and its unit after a number, `review 3 rounds · executor 300 lines ·
// orchestrator off`.
func limitsSaid(numbers config.Numbers) string {
	var said []string
	for _, limit := range numbers.Limits() {
		words := limitNames[limit.Key]
		text := words.short + " " + limitShown(limit.Value)
		switch number, whole := limit.Value.(int); {
		case number == 1:
			text += " " + strings.TrimSuffix(words.unit, "s")
		case whole && number != 0:
			text += " " + words.unit
		}
		said = append(said, text)
	}
	return strings.Join(said, " · ")
}

// limitShown is a number as `Limits` says it, Python's menu.limit_shown: 0, the limit off, as `off`.
func limitShown(value any) string {
	if value == 0 {
		return "off"
	}
	return fmt.Sprint(value)
}

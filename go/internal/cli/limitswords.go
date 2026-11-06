package cli

import (
	"fmt"
	"strings"

	"agentkit/internal/config"
)

// limitsSaid is `Limits`' value on `c`, Python's menu.limits_value: each number in force under its
// short name, `off` for zero and its unit after a number, `review 3 rounds · executor 300 lines ·
// orchestrator off`.
func limitsSaid(numbers config.Numbers) string {
	var said []string
	for _, each := range []struct {
		short, unit string
		value       any
	}{{"review", "rounds", numbers.Rounds}, {"executor", "lines", numbers.ReviewLines.Said()}, {"orchestrator", "lines", numbers.SeatLines.Said()}} {
		number, whole := each.value.(int)
		if number == 1 {
			each.unit = strings.TrimSuffix(each.unit, "s")
		}
		switch {
		case whole && number == 0:
			said = append(said, each.short+" off")
		case whole:
			said = append(said, fmt.Sprintf("%s %d %s", each.short, number, each.unit))
		default:
			said = append(said, fmt.Sprintf("%s %v", each.short, each.value))
		}
	}
	return strings.Join(said, " · ")
}

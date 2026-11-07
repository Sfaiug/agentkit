package cli

import (
	"cmp"
	"fmt"
	"math"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// menuLimits is `Limits` on `c` (menu.config_limits): each of config's numbers a row under its
// plain name (limitNames), its value and `default N` where that is not ak's default, and its own
// note, what it means and the board rows it moves; under `Review rounds`' how the runs ended, read
// as the page opens.  ← and → move the pointed one a step (limitStep), saved to config.toml at
// once.  The rows are read once and again after each save, as Python's page reads the config it
// holds.
func menuLimits(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	ended := history.RoundEndings()
	var rows []menu.PageRow // as last read
	return configPage("limits", "", func() ([]menu.PageRow, bool) {
		if rows != nil {
			return rows, true
		}
		numbers, err := config.HostNumbers()
		if err != nil {
			return nil, false
		}
		for _, limit := range numbers.Limits() {
			words := limitNames[limit.Key]
			row := menu.PageRow{Label: words.name, Value: limitShown(limit.Value), Note: words.off,
				Step: func(by int) func() string {
					value := limitStep(limit.Key, limit.Value, by)
					if value == nil {
						return nil
					}
					return func() string {
						rows = nil
						return saved(config.SaveLimit(limit.Key, value, seat.KeepConfigEfforts))
					}
				}}
			if limit.Value != limit.Default {
				row.Aside = fmt.Sprint("default ", limit.Default)
			}
			if limit.Value != 0 {
				row.Note = fmt.Sprintf("%s%s; it moves %s.", strings.ToUpper(limit.Meaning[:1]), limit.Meaning[1:], strings.Join(limit.Moves, ", "))
			}
			if limit.Key == "review_rounds" {
				row.Under = func(s terminal.Screen) []string { return menu.RoundsChart(s, ended) }
			}
			rows = append(rows, row)
		}
		return rows, true
	}, keyboard, painter, "limit", "value")
}

// limitStep is `key`'s step (limitNames) next from `held`, up for `by` 1 and down for -1, Python's
// menu.limit_step: one between steps, as typed by hand, moves onto the next; nil past an end.
func limitStep(key string, held any, by int) any {
	steps := limitNames[key].steps
	for i := range steps {
		if by < 0 {
			i = len(steps) - 1 - i
		}
		if cmp.Compare(limitRank(steps[i]), limitRank(held)) == by {
			return steps[i]
		}
	}
	return nil
}

// limitRank orders a limit's values: the numbers up, then a line limit's "no limit".
func limitRank(value any) int {
	if number, whole := value.(int); whole {
		return number
	}
	return math.MaxInt
}

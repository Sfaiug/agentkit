package cli

import (
	"cmp"
	"fmt"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// menuLimits is `Limits` on `c` (menu.config_limits): each of config's numbers a row under its
// plain name (limitNames), its value and `default N` where that is not ak's default, and under the
// rows the pointed one's lines: what it means, as a sentence of its own, then under `Review
// rounds`' how the runs ended, and under each line limit how changes of each size did at its
// value, read as the page opens.  ← and → move the pointed one a step (limitStep), saved to
// config.toml at once.  The rows are read once and again after each save, as Python's page reads
// the config it holds.
func menuLimits(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	ended := history.RoundEndings()
	builds, own := history.FirstReviewSizes()
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
			row := menu.PageRow{Label: words.name, Value: limitShown(limit.Value),
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
			if limit.Value == 0 { // what off does, said as its note until its lines say it (milestone 207h)
				row.Note = words.off
			}
			var chart func(terminal.Screen) []string
			switch limit.Key {
			case "review_rounds":
				chart = func(s terminal.Screen) []string { return menu.RoundsChart(s, ended) }
			case "executor_lines":
				chart = func(s terminal.Screen) []string {
					return menu.SizeChart(s, builds, limit.Value, 100, "how often a build passed its first review, by size", "build")
				}
			case "orchestrator_lines":
				chart = func(s terminal.Screen) []string {
					return menu.SizeChart(s, own, limit.Value, 25, "how often an orchestrator's own pull request merged in its first round, by size", "")
				}
			}
			meant := strings.ToUpper(limit.Meaning[:1]) + limit.Meaning[1:] + "."
			row.Under = func(s terminal.Screen) []string { return append(menu.Told(s, meant), chart(s)...) }
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
		if limitOrder(steps[i], held) == by {
			return steps[i]
		}
	}
	return nil
}

// limitOrder orders two of a limit's values: the numbers up, then a line limit's "no limit" over
// every number, the largest too.
func limitOrder(a, b any) int {
	x, xNumber := a.(int)
	y, yNumber := b.(int)
	if xNumber != yNumber {
		if xNumber {
			return -1
		}
		return 1
	}
	return cmp.Compare(x, y)
}

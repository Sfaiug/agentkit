package cli

import (
	"cmp"
	"fmt"
	"math"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// menuLimits is `Limits` on `c` (menu.config_limits): each of config's numbers a row under its
// plain name (limitNames), its value and `default N` where that is not ak's default, and its own
// note, what it means and the board rows it moves, with how the runs ended under `Review rounds`',
// read as the page opens.  Enter opens its choices, ● the value in force, and a pick saves it to
// config.toml at once.  The rows are read once and again after each save, as Python's page reads
// the config it holds.
func menuLimits(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	ended := history.RoundEndings()
	var rows []menu.PageRow // as last read
	choices := func(at int) ([]menu.PageRow, bool) {
		numbers, err := config.HostNumbers()
		if err != nil {
			return nil, false
		}
		limit := numbers.Limits()[at]
		values := slices.Clone(limitNames[limit.Key].offered)
		if !slices.Contains(values, limit.Value) {
			values = append(values, limit.Value)
		}
		slices.SortFunc(values, func(a, b any) int { return cmp.Compare(limitRank(a), limitRank(b)) })
		var list []menu.PageRow
		for _, value := range values {
			list = append(list, menu.PageRow{Value: limitShown(value), On: value == limit.Value, Flip: func() string {
				rows = nil
				return saved(config.SaveLimit(limit.Key, value, seat.KeepConfigEfforts))
			}})
		}
		return list, true
	}
	return configPage("limits", "", func() ([]menu.PageRow, bool) {
		if rows != nil {
			return rows, true
		}
		numbers, err := config.HostNumbers()
		if err != nil {
			return nil, false
		}
		for at, limit := range numbers.Limits() {
			words := limitNames[limit.Key]
			row := menu.PageRow{Label: words.name, Value: limitShown(limit.Value), Note: words.off,
				List: func() ([]menu.PageRow, bool) { return choices(at) }}
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
	}, keyboard, painter)
}

// limitRank orders a list's values: the numbers up, then a line limit's "no limit".
func limitRank(value any) int {
	if number, whole := value.(int); whole {
		return number
	}
	return math.MaxInt
}

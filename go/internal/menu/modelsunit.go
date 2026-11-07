package menu

import "slices"

// Each role's cost column is headed with its unit (quality.Said's CostUnit), and under a role
// priced in week shares the legend says that only a row noted `measured` was measured; the others
// are its board price scaled by measured rows.  Owner, 3 Nov 2026: a cost on screen must never
// look more certain than it is.
var (
	units       = map[string]string{"share": "week %", "money": "plan $", "board_dollars": "a task"}
	shareLegend = [2]string{units["share"], "a task's share of its subscription's week: measured " +
		"where the row says so, else its board price scaled by the rows that were"}
)

// headed is whether role heads the columns: it has rows in another unit than unit, the last role
// with rows' ("" before the first).
func headed(role Role, unit string) bool {
	return len(role.Lines) > 0 && role.Unit != unit
}

// legendOf is the legend under said, the week share's line where a role is priced in them.
func legendOf(said []Role) [][2]string {
	if slices.ContainsFunc(said, func(role Role) bool { return role.Unit == shareLegend[0] }) {
		return slices.Concat(legend, [][2]string{shareLegend})
	}
	return legend
}

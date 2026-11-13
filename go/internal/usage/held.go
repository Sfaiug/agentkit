package usage

import (
	"fmt"
	"strconv"

	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// heldText is `week ≈ $2010 at list prices`, what all of the meter's window holds in the login's
// plan, its Week, in whole dollars, Python's usage._held: `-` while the plan has none.  A window
// that is not a week says its length: `30d`.
func heldText(screen terminal.Screen, plan Plan, meter *run.Object) string {
	dollars, held := plan.Week()
	if !held {
		return "-"
	}
	named := "week"
	if window, sized := reading(meter, "window_secs"); sized && window != 7*86400 {
		named = terminal.FormatAge(window)
	}
	// 'f' with no places rounds half to even, as Python's :.0f does
	return fmt.Sprintf("%s %s $%s at list prices", named, about(screen), strconv.FormatFloat(dollars, 'f', 0, 64))
}

// about is the glyph an estimate is said with.
func about(screen terminal.Screen) string {
	if screen.ASCII() {
		return "~"
	}
	return "≈"
}

// digits is a price in plain digits, never an exponent, and `-` for none, Python's usage._digits.
func digits(price *float64) string {
	if price == nil {
		return "-"
	}
	return grouped(strconv.FormatFloat(*price, 'f', -1, 64))
}

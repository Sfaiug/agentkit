package screen

import "agentkit/internal/config"

// InComposer is whether row `at` of a capture (`capture-pane -p`, its leading blank rows kept)
// lies in the composer's box, the bottom run of rows the `composer` pattern reads whole
// (watch.off_composer): false where no row is one.
func (r *Rules) InComposer(shown string, at int) bool {
	rows := config.SplitLines(shown)
	inside := func(row int) bool { return r.composer != nil && r.composer.MatchString(Plain(rows[row])) }
	bottom := len(rows) - 1
	for bottom >= 0 && !inside(bottom) {
		bottom--
	}
	top := bottom
	for top > 0 && inside(top-1) {
		top--
	}
	return bottom >= 0 && top <= at && at <= bottom
}

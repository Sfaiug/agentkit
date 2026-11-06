package size

import (
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// Seat is the added lines a seat's change from where head left base has its first review read,
// Python's seat_lines: those Added counts less those Reviewed finds carried, and whether they are
// more than limit, the seat's orchestrator_lines.  0 is a seat that builds nothing, so a change
// adding no line is too much there as well.  The gate before a seat's own pull request's first
// review and the gh guard at its `gh pr create` both ask here, so the two never disagree.
func Seat(g gitcall.Git, base, head string, limit config.Lines) (int, bool, error) {
	lines, err := Added(g, base, head)
	if err != nil {
		return 0, false, err
	}
	_, carried, err := Reviewed(g, base, head)
	if err != nil {
		return 0, false, err
	}
	most, limited := limit.Most()
	counted := lines - carried
	return counted, limited && (most == 0 || counted > most), nil
}

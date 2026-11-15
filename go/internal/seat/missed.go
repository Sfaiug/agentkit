package seat

import (
	"slices"

	"agentkit/internal/run"
)

// missed is the news watch.news_owed reads before any look has read the seat's screen: a line ak
// owes it, which owns its next prompt, so no `continue` goes in ahead of it.  A move's (`switch`)
// tells it nothing.  "" for none.
func (facts climbing) missed() string {
	if slices.ContainsFunc(facts.file.List("owed_lines"), func(line any) bool {
		owed, ok := line.(*run.Object)
		return !ok || !owed.Truthy("switch")
	}) {
		return "telling it what it missed while it was gone"
	}
	return ""
}

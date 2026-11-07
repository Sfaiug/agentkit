package seat

import (
	"slices"

	"agentkit/internal/run"
)

// movesUntyped is whether the seat is owed a move's line (`switch`), which only Python queues
// for a harness Go types nothing into: Python sends it.
func movesUntyped(name string, file *run.Object) bool {
	if file == nil || !slices.ContainsFunc(file.List("owed_lines"), func(line any) bool { return line.(*run.Object).Truthy("switch") }) {
		return false
	}
	own, _ := seatHarness(name)
	return !typable(own)
}

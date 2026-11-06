package seat

import (
	"slices"

	"agentkit/internal/run"
)

// launch holds the typing lock: commands naming the old harness's pane must
// never reach its replacement. Other instructions stay owed, as orch.launch keeps them.
func retireSwitchLines(name string) error {
	return changeOwed(name, func(lines []any) []any {
		return slices.DeleteFunc(slices.Clone(lines), func(value any) bool {
			line, ok := value.(*run.Object)
			return ok && line.Truthy("switch")
		})
	})
}

package seat

import (
	"path/filepath"
	"slices"

	"agentkit/internal/run"
)

// launch holds the typing lock: commands naming the old harness's pane must
// never reach its replacement. Other instructions stay owed, as orch.launch keeps them.
func retireSwitchLines(state, name string) error {
	return put(filepath.Join(state, "seat-"+name+".json"), filepath.Join(state, "seat-"+name+".lock"), run.Line, false, func(data *run.Object) bool {
		lines := data.List("owed_lines")
		kept := slices.DeleteFunc(slices.Clone(lines), func(value any) bool {
			line, ok := value.(*run.Object)
			return ok && line.Truthy("switch")
		})
		if len(kept) == len(lines) {
			return false
		}
		var owed any
		if len(kept) > 0 {
			owed = kept
		}
		return set([]field{{"owed_lines", owed}}, field{"session", name})(data)
	})
}

package helper

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/machines"
)

// takers are the machines config.toml names that take work, "tests" or "turns", as Python's
// _takers has machines.work read their marks: turns never on one whose probe last said macOS.
func takers(work string) []string {
	named := config.MachineNames()
	var aliases []string
	for _, machine := range machines.Known() {
		if marks, _ := machine.Work(); slices.Contains(named, machine.Name) && slices.Contains(marks, work) {
			aliases = append(aliases, machine.Name)
		}
	}
	return aliases
}

package machines

import "slices"

// TakesTurns is whether a model turn may go to another machine, as Python's machine_turn.call
// sends one: a machine besides this one whose marks it takes turns by.  Go runs every turn here.
func TakesTurns() bool {
	for _, machine := range Known() {
		if work, _ := machine.Work(); machine.Name != Here && slices.Contains(work, "turns") {
			return true
		}
	}
	return false
}

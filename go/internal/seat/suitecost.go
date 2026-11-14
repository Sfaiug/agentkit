package seat

import "strings"

// suiteCost is whether a state/ entry is a suite's measured cost, `suite-<key>.json`, which a
// lander keeps as it checks a line (gate.suite_cost) and no seat's word hangs on.  The loop
// package names it and imports this one, so it is named here too.
func suiteCost(name string) bool {
	return strings.HasPrefix(name, "suite-") && strings.HasSuffix(name, ".json")
}

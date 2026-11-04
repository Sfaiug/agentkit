package harness

// Antigravity's screen says its word; its launch and conversation store stay Python's.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, record: antigravityRecord,
		keys: []string{"antigravity_launch", "antigravity_open"}, kept: antigravityKept}
}

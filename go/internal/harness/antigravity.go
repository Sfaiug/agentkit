package harness

// Antigravity's launcher-owned conversations reopen without learning an id from its SQLite store.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, record: antigravityRecord,
		launch: antigravityLaunch,
		keys:   []string{"antigravity_launch", "antigravity_open"}, kept: antigravityKept}
}

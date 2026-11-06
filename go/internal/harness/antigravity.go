package harness

// Antigravity's launcher-owned conversations reopen without learning an id from its SQLite store,
// which Go reads for what was said in them, by whom and when, and which model answered last.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, record: antigravityRecord,
		launch: antigravityLaunch, interactive: antigravityInteractive, report: antigravityReported,
		said: antigravitySaid, typed: antigravityTyped,
		keys: []string{"antigravity_launch", "antigravity_open"}, kept: antigravityKept}
}

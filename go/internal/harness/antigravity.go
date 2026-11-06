package harness

// Antigravity's launcher-owned conversations reopen without learning an id from its SQLite store,
// whose steps say what they hold and who typed what when.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, record: antigravityRecord,
		launch: antigravityLaunch, interactive: antigravityInteractive, report: antigravityReported,
		said: antigravitySaid, typed: antigravityTyped,
		keys: []string{"antigravity_launch", "antigravity_open"}, kept: antigravityKept}
}

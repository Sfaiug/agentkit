package harness

// An Antigravity seat owns its launcher's conversation, or the one its own agy holds open, learned
// from /proc; Go reads its SQLite store for what was said in it, by whom and when, and which model
// answered last.  Go opens a new seat; reopening one stays Python's.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, anew: true, record: antigravityRecord, owned: antigravityOwned,
		launch: antigravityLaunch, interactive: antigravityInteractive, report: antigravityReported,
		said: antigravitySaid, typed: byName(antigravityTyped),
		keys: []string{"antigravity_launch", "antigravity_open"}, kept: antigravityKept}
}

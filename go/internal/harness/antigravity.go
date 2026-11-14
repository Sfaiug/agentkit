package harness

// An Antigravity seat owns its launcher's conversation, one its own agy took a prompt in, or the one
// its own agy holds open, learned from /proc; Go reads its SQLite store for what was said in it, by whom and when, the owner's
// answers on its question cards, and which model answered last.  Go opens a new seat; reopening
// one stays Python's.
func init() {
	plugins["antigravity"] = plugin{seats: true, looks: true, anew: true, record: antigravityRecord, owned: antigravityOwned, found: antigravityFound, named: antigravityNamed,
		launch: antigravityLaunch, interactive: antigravityInteractive, report: antigravityReported, lend: antigravityLend,
		said: antigravitySaid, typed: byName(antigravityTyped), answered: antigravityRead,
		keys: []string{"antigravity_launch", "antigravity_open"}}
}

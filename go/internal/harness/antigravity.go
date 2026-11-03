package harness

// Antigravity's launch writes down more than the launcher's id (agentkit/harness/antigravity.py's
// `launched`), so Go does not open its seats yet.
func init() { plugins["antigravity"] = plugin{} }

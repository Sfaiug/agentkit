package harness

// A Codex seat owns a conversation only by a launch receipt (codex.py `conversation`), which no
// record Go follows names, so it starts fresh; Python then writes `resumable: false` into its
// record (codex.py `reconcile`), a record Go does not follow.
func init() { plugins["codex"] = plugin{seats: true, fresh: "starts a new Codex conversation"} }

package harness

// LaunchKeys are what a launch writes into a seat's record about the conversation it owns
// (harness.LAUNCH_KEYS): evidence of the conversation it is on now, which no earlier one of the
// seat's is read by.
var LaunchKeys = []string{"conversation", "resumable", "id_source", "before", "codex_launch", "codex_history",
	"opencode_launch", "muse_launch", "antigravity_launch", "antigravity_open", "session_title", "title_sync"}

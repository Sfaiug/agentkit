package harness

import (
	"path/filepath"
	"regexp"

	"agentkit/internal/config"
)

// keptIn is the folder of state/ that holds ak's names, an entry Claude keeps beside its seats'
// records (KeptInState).
const keptIn = "conversations"

var claudeKeptIn = regexp.MustCompile("^" + keptIn + "$")

// claudeKept is ak's own name for that conversation's transcript, which the tick gives it
// (claude.py `kept`).
func claudeKept(conversation string) string {
	return filepath.Join(config.Home(), "state", keptIn, "claude-"+conversation+".jsonl")
}

var keptFile = regexp.MustCompile(`^claude-(.+)\.jsonl$`)

// claudeStore is ak's names (claude.py `conversation_stores`): Claude ends its own transcripts,
// never these, each a second name of one while Claude keeps it.
func claudeStore() Store {
	copies := claudeKept("*")
	return Store{"claude", filepath.Dir(copies), filepath.Base(copies), keptFile, 2}
}

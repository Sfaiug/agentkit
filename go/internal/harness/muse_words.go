package harness

import (
	"regexp"

	"agentkit/internal/run"
)

var museSession = regexp.MustCompile(`^[\p{L}\p{N}_-]+$`)
var museKept = regexp.MustCompile(`^muse-launch-[0-9a-f]{32}(?:\.gone)?$`)

// museRecord leaves the record as Python reconciles it: Go reads the seat's session off its receipt
// (museConversation), and that session's question card, words and model off Muse's own log.
func museRecord(_ string, _ *run.Object) (plugin, bool) {
	return plugins["muse"], true
}

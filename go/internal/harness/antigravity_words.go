package harness

import (
	"regexp"

	"agentkit/internal/run"
)

var antigravityKept = regexp.MustCompile(`^antigravity-claim\.lock$`)
var antigravityConversation = regexp.MustCompile(`^[\pL\pN_-]+$`)

// antigravityRecord admits launcher conversations, their last answer read from their store
// (antigravity.py `owned`, `store`, `running`), and a launch that learns none. A learned
// conversation stays Python's, even after its store is gone, as does one a launch would learn now,
// before it is written down: the listing only follows ids in `conversation`.
func antigravityRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["antigravity"]
	conversation := record.Str("conversation")
	if record.Str("id_source") != "launcher" || conversation == "" {
		return own, antigravityLearn(record) == ""
	}
	path := antigravityStore(conversation)
	if path == "" {
		return own, true
	}
	return antigravityStored(own, conversation, path)
}

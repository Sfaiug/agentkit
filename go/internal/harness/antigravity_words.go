package harness

import (
	"regexp"

	"agentkit/internal/run"
)

// antigravityKept is the claim's lock, and the folder adapters/antigravity.sh makes each launch's
// agent and hooks in, which no seat's word hangs on.
var antigravityKept = regexp.MustCompile(`^antigravity(?:-claim\.lock)?$`)
var antigravityConversation = regexp.MustCompile(`^[\pL\pN_-]+$`)

// antigravityRecord admits the conversation the seat owns, its launcher's or the one its launch's
// own agy holds open, learned once here, and its last answer read from its store (antigravity.py
// `conversation`, `store`, `running`): the seat may resume it, and its status line reports for it.
func antigravityRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["antigravity"]
	own.owning = antigravityKnown
	own.resumable = func(current *run.Object) bool { return antigravityKnown(current) != "" }
	conversation := antigravityLearn(record)
	path := antigravityStore(conversation)
	if path == "" {
		return own, true
	}
	return antigravityStored(own, conversation, path)
}

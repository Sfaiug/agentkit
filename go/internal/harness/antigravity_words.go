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
// Any copy of the record the listing asks about owns what that copy says, else what was learned
// here for its launch, which a claim written since this copy was read does not take away.
func antigravityRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["antigravity"]
	conversation, launch := antigravityLearn(record, true), record.Get("antigravity_launch")
	owning := func(current *run.Object) string {
		if mine := antigravityMine(current); mine != "" || !run.Equal(current.Get("antigravity_launch"), launch) {
			return mine
		}
		return conversation
	}
	own.owning, own.resumable = owning, func(current *run.Object) bool { return owning(current) != "" }
	path := antigravityStore(conversation)
	if path == "" {
		return own, true
	}
	return antigravityStored(own, conversation, path)
}

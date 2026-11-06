package harness

import (
	"path/filepath"
	"regexp"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

var antigravityKept = regexp.MustCompile(`^antigravity-claim\.lock$`)
var antigravityConversation = regexp.MustCompile(`^[\pL\pN_-]+$`)

// antigravityRecord admits launcher conversations, their last answer read from their store
// (antigravity.py `owned`, `store`, `running`). Learned conversations stay Python's even after
// their store is gone: the listing only follows ids in `conversation`.
func antigravityRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["antigravity"]
	conversation := record.Str("conversation")
	if record.Str("id_source") != "launcher" {
		conversation = ""
		if seen := record.Dict("antigravity_open"); seen != nil && run.Equal(seen.Get("launch"), record.Get("antigravity_launch")) && seen.Truthy("conversation") {
			return own, false
		}
	}
	if conversation == "" {
		_, pending := record.Get("antigravity_launch").(string)
		return own, !pending
	}
	if !antigravityConversation.MatchString(conversation) {
		return own, true
	}
	return antigravityStored(own, conversation, filepath.Join(config.UserHome(), ".gemini", "antigravity-cli", "conversations", conversation+".db"))
}

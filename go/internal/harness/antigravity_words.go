package harness

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

var antigravityKept = regexp.MustCompile(`^antigravity-claim\.lock$`)
var antigravityConversation = regexp.MustCompile(`^[\pL\pN_-]+$`)

// antigravityRecord admits launcher screens without a conversation store to read for their
// last answer (antigravity.py `owned`, `store`, `running`). Learned conversations stay Python's
// even after their store is gone: the listing only follows ids in `conversation`. This decision
// belongs to its reconciliation boundary, even if a store appears before the word is published.
func antigravityRecord(record *run.Object) (plugin, bool) {
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
	_, err := os.Stat(filepath.Join(config.UserHome(), ".gemini", "antigravity-cli", "conversations", conversation+".db"))
	return own, errors.Is(err, fs.ErrNotExist)
}

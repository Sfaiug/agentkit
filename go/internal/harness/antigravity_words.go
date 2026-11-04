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

// antigravityRecord admits the screen where Python has no conversation store to read for its
// last answer (antigravity.py `owned`, `store`, `running`). Learning a pending launch's open
// conversation and reading SQLite stay Python's. This decision belongs to the listing's
// reconciliation boundary, even if a store appears while its word waits to be published.
func antigravityRecord(record *run.Object) (plugin, bool) {
	own := plugins["antigravity"]
	conversation := record.Str("conversation")
	if record.Str("id_source") != "launcher" {
		conversation = ""
		if seen := record.Dict("antigravity_open"); seen != nil && run.Equal(seen.Get("launch"), record.Get("antigravity_launch")) {
			conversation = seen.Str("conversation")
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

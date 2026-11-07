package harness

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// claudeReadBy is the file that conversation's transcript is read by (claude.py `read_by`):
// Claude's own while it is there, else ak's name for it (`kept`), a link to the same file that
// stays once Claude's cleanup deleted its own; Claude's own where neither is there.
func claudeReadBy(record map[string]any) string {
	own := claudeConversation(record)
	if _, err := os.Stat(own); own == "" || !errors.Is(err, fs.ErrNotExist) {
		return own
	}
	conversation, _ := record["conversation"].(string)
	kept := filepath.Join(config.Home(), "state", "conversations", "claude-"+conversation+".jsonl")
	if _, err := os.Stat(kept); errors.Is(err, fs.ErrNotExist) {
		return own
	}
	return kept
}

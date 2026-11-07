package harness

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// TokenSources is the files that harness keeps a seat's spent tokens in, its plugin's
// `seat_token_sources`: none where the record names no conversation; false where Go does not name
// them, for that harness or for this record.
func TokenSources(name string, record map[string]any) ([]string, bool) {
	if hook := plugins[name].sources; hook != nil {
		return hook(record)
	}
	return nil, false
}

// claudeSources is where Claude Code keeps them (claude.py `seat_token_sources`): the seat's
// conversation, and its subagents' in the folder beside it, which Go does not walk: false where
// that stands.
func claudeSources(record map[string]any) ([]string, bool) {
	path := claudeConversation(record)
	if path == "" {
		return nil, true
	}
	_, err := os.Lstat(filepath.Join(strings.TrimSuffix(path, ".jsonl"), "subagents"))
	return []string{path}, errors.Is(err, fs.ErrNotExist)
}

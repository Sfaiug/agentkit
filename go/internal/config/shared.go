package config

import (
	"encoding/json"
	"fmt"
	"os"
	"unicode/utf8"

	"agentkit/internal/parsed"
)

// stateNames is the state directory's names in name order, listed again only once it changed
// (Python's config.seat_files): every reader's, so only read.
var stateNames = parsed.Of(func(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	names := make([]string, len(entries))
	for at, entry := range entries {
		names[at] = entry.Name()
	}
	return names, err
})

// sessionFiles is what each session file holds, a rename pointer's among them, parsed again only
// once it changed (Python's config._session_json): every reader's, so only read.
var sessionFiles = parsed.Of(func(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if !utf8.Valid(data) {
		return nil, fmt.Errorf("%s: invalid UTF-8", path)
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	record, _ := value.(map[string]any)
	return record, nil
})

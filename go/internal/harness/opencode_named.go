package harness

import (
	"cmp"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

// opencodeNamed is opencodeFound, naming none only where its launch's receipt holds no session
// file: one there that names no session is an error too.
func opencodeNamed(record map[string]any) (string, error) {
	session, err := opencodeFound(record)
	token, _ := record["opencode_launch"].(string)
	if session != "" || err != nil || !launchToken.MatchString(token) {
		return session, err
	}
	path := filepath.Join(opencodeReceipt(token), "session")
	if _, err := os.Stat(path); !errors.Is(err, fs.ErrNotExist) {
		return "", cmp.Or(err, fmt.Errorf("%s names no OpenCode session", path))
	}
	return "", nil
}

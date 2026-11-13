package harness

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

// museNamed is the session the seat's launch reported (museConversation), never followed on, so
// asking writes nothing.
func museNamed(record map[string]any) (string, error) {
	token, _ := record["muse_launch"].(string)
	return museNames(museReceipt(token), "session")
}

// museFound is museConversation, and the error of a launch receipt whose session file is there and
// names no session (museNames).
func museFound(record map[string]any) (string, error) {
	if _, err := museNamed(record); err != nil {
		return "", err
	}
	return museConversation(record), nil
}

// museNames is museRead, and the error of a file there that names no session: one that cannot be
// read, is not UTF-8 or holds anything else.
func museNames(receipt, name string) (string, error) {
	if receipt == "" {
		return "", nil
	}
	path := filepath.Join(receipt, name)
	session, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return "", nil
	case err != nil:
		return "", err
	case !museSession.Match(session): // bytes that are not UTF-8 match no letter
		return "", fmt.Errorf("%s names no Muse session", path)
	}
	return string(session), nil
}

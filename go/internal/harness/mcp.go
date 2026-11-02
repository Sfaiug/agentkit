package harness

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/task"
)

// ErrPython leaves registering to Python ak: a config it reads and Go cannot keep or word as it
// does.
var ErrPython = errors.New("left to Python")

// A Server is one MCP server a harness is pointed at: by its URL, or as the command that serves it.
type Server struct {
	Name, URL, Command string
	Args               []string
	Env                map[string]string
}

// RegisterMCP points that harness at the servers in its own config, as Python's plugin
// `register_mcp`: what it did and where, "" where it writes no MCP entry.
func RegisterMCP(name string, servers []Server) (string, error) {
	if hook := plugins[name].registerMCP; hook != nil {
		return hook(servers)
	}
	return "", nil
}

// readConfig is a harness's config as Python's read_text reads it; false where there is none.
func readConfig(path string) (string, bool, error) {
	data, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return "", false, nil
	case err != nil:
		return "", false, fmt.Errorf("cannot read %s: %s", path, config.PyError(err))
	case !utf8.Valid(data):
		return "", false, ErrPython
	}
	return task.Text(data), true, nil
}

// writeConfig replaces a harness's config through a rename, so no reader ever meets half of one:
// from a temporary file no other launch shares, with the mode the old file had, a new one's
// owner-only as the temporary file is made.
func writeConfig(path, text string) error {
	temp, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err == nil {
		defer os.Remove(temp.Name())
		_, err = temp.WriteString(text)
		err = errors.Join(err, temp.Close())
	}
	if err == nil {
		if info, stat := os.Stat(path); stat == nil {
			err = os.Chmod(temp.Name(), info.Mode().Perm())
		}
	}
	if err == nil {
		err = os.Rename(temp.Name(), path)
	}
	if err != nil {
		return fmt.Errorf("cannot write %s: %s", path, config.PyError(err))
	}
	return nil
}

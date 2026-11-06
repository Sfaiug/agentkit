package harness

import (
	"os"
	"path/filepath"
)

// TurnFailed leaves in a failed turn's out-dir what its harness said of why only in the last
// result event of its stdout, nil for none, as Python's adapter `run` does: a worker reads a
// turn's words from stderr.log alone.
func TurnFailed(name, out string, result map[string]any) {
	if hook := plugins[name].failed; hook != nil {
		hook(out, result)
	}
}

// claudeFailed appends to stderr.log the words of a result Claude Code marks an error, as
// claude.sh's `run`: they are all Claude Code 2.1.316 says of a revoked login, with stderr empty,
// and the worker reads a dead login there by the manifest's `[auth] signatures`.
func claudeFailed(out string, result map[string]any) {
	said, ok := result["result"].(string)
	if result["is_error"] != true || !ok {
		return
	}
	if log, err := os.OpenFile(filepath.Join(out, "stderr.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666); err == nil {
		log.WriteString(said + "\n")
		log.Close()
	}
}

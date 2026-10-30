// Package harness holds what a harness brings beyond its adapter's manifest, as Python's
// agentkit/harness/<name>.py does: each hook answered by that harness's own where it has one,
// by the default elsewhere.
package harness

import (
	"cmp"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// A plugin is one harness's own answers; a hook it leaves nil takes the default.
type plugin struct {
	identity  func(text string, argv []string) (string, bool)
	snapshots bool
}

var plugins = map[string]plugin{}

// Identity is a harness's `[update] version` output as a build identity, refined where it has
// more to say; false where it reads what Go cannot read as Python does.
func Identity(name, text string, argv []string) (string, bool) {
	if hook := plugins[name].identity; hook != nil {
		return hook(text, argv)
	}
	return text, true
}

// Snapshots is whether an upgrade of that harness is put back from a local snapshot it takes
// itself; otherwise its `[update] revert` puts it back, or nothing can.
func Snapshots(name string) bool {
	return plugins[name].snapshots
}

// Binary is the program a harness's command names, found as its adapter finds it, as Python's
// config.harness_binary: on PATH first, else in an installer's own folder no fresh shell has on
// PATH; a path answers for itself.  "" where it is not found.
func Binary(name string) string {
	if strings.Contains(name, "/") {
		if _, err := exec.LookPath(name); err == nil {
			return name
		}
		return ""
	}
	// Python's which takes a relative PATH entry as it takes any other
	if found, err := exec.LookPath(name); err == nil || errors.Is(err, exec.ErrDot) {
		return found
	}
	home, _ := os.UserHomeDir()
	for _, dir := range []string{filepath.Join(home, ".opencode", "bin"),
		cmp.Or(os.Getenv("GROK_BIN_DIR"), filepath.Join(home, ".grok", "bin")),
		filepath.Join(home, ".local", "bin"), filepath.Join(home, ".npm-global", "bin")} {
		if found, err := exec.LookPath(filepath.Join(dir, name)); err == nil {
			return found
		}
	}
	return ""
}

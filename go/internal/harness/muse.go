package harness

import (
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
)

// Muse's channel installer deletes the build it replaces and offers no versioned reinstall, so
// only a snapshot puts it back.
func init() { plugins["muse"] = plugin{identity: museIdentity, snapshots: true} }

// museIdentity is Muse's release label plus the build its launcher installed, which the launcher
// records beside itself: the label alone cannot tell a frozen installed release from the next.
func museIdentity(text string, argv []string) (string, bool) {
	launcher := config.Resolve(Binary(argv[0]))
	data, err := os.ReadFile(filepath.Join(filepath.Dir(launcher), ".muse-version"))
	if err != nil {
		return text, true
	}
	if !utf8.Valid(data) {
		return "", false
	}
	build := strings.TrimFunc(string(data), config.Space)
	if build == "" || strings.Contains(text, build) {
		return text, true
	}
	return text + " (installed build " + build + ")", true
}

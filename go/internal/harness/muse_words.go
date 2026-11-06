package harness

import (
	"os"
	"path/filepath"
	"regexp"

	"agentkit/internal/run"
)

var museSession = regexp.MustCompile(`^[\p{L}\p{N}_-]+$`)
var museKept = regexp.MustCompile(`^muse-launch-[0-9a-f]{32}(?:\.gone)?$`)

// museRecord admits the screen until this launch reports a session (muse.py `conversation`).
// Its registry, question cards and conversation stay Python's once it does. A report arriving
// while the listing publishes belongs to the next listing, and no record is rewritten here.
func museRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["muse"]
	path := museReceipt(record.Str("muse_launch"))
	if path == "" {
		return own, true
	}
	session, err := os.ReadFile(filepath.Join(path, "session"))
	return own, err != nil || !museSession.Match(session)
}

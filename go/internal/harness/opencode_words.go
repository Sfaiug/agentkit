package harness

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

var opencodeSession = regexp.MustCompile(`^ses_[0-9A-Za-z]+$`)
var opencodeKept = regexp.MustCompile(`^opencode-launch-[0-9a-f]{32}(?:\.gone)?$`)

// opencodeRecord admits the screen until this launch reports a session (opencode.py
// `conversation`). Once it does, its database and any reconciliation stay Python's. The
// listing keeps this decision even if the plugin reports while it waits to publish the word.
func opencodeRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["opencode"]
	token := record.Str("opencode_launch")
	if !launchToken.MatchString(token) {
		return own, true
	}
	session, err := os.ReadFile(filepath.Join(config.Home(), "state", "opencode-launch-"+token, "session"))
	return own, err != nil || !opencodeSession.MatchString(strings.TrimFunc(string(session), config.Space))
}

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

// opencodeRecord reads what opencode.db says of the session this launch reported (opencode.py
// `conversation`), the seat's own and resumable, once for the whole listing: a report or a row
// landing while it waits to publish the word is the next listing's.  False where Go cannot read
// that database as Python does.
func opencodeRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["opencode"]
	token := record.Str("opencode_launch")
	if !launchToken.MatchString(token) {
		return own, true
	}
	reported, err := os.ReadFile(filepath.Join(config.Home(), "state", "opencode-launch-"+token, "session"))
	session := strings.TrimFunc(string(reported), config.Space)
	if err != nil || !opencodeSession.MatchString(session) {
		return own, true
	}
	turn, known := opencodeRead(session)
	// a record that names another launch since is another session's
	this := func(current *run.Object) bool { return current.Str("opencode_launch") == token }
	own.resumable = this
	own.recorded = func(current *run.Object) (string, bool) {
		if !this(current) || !turn.ended {
			return "", false
		}
		return turn.said, true
	}
	own.answer = func(current *run.Object) (any, any, any, bool) {
		if !this(current) || !turn.answered {
			return nil, nil, nil, false
		}
		return turn.model, turn.effort, turn.at, true
	}
	return own, known
}

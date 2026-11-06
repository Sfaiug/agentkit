package harness

import (
	"regexp"

	"agentkit/internal/run"
)

var opencodeKept = regexp.MustCompile(`^opencode-launch-[0-9a-f]{32}(?:\.gone)?$`)

// opencodeRecord reads what opencode.db says of the session this launch reported (opencode.py
// `conversation`), the seat's own and resumable, once for the whole listing: a report or a row
// landing while it waits to publish the word is the next listing's.  False where Go cannot read
// that database as Python does.
func opencodeRecord(_ string, record *run.Object) (plugin, bool) {
	own := plugins["opencode"]
	token := record.Str("opencode_launch")
	session := opencodeConversation(map[string]any{"opencode_launch": token})
	if session == "" {
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

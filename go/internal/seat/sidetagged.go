package seat

import (
	"strings"

	"agentkit/internal/tmux"
)

// sideSession is whether a session neither ak opened nor a record names is one a seat started,
// which carries that seat's tag in its own environment: closeSideSessions passes over any other,
// as Python's sweep_finished does, so only a tagged one is a session maintenance may close.
func sideSession(name string) bool {
	tag, err := tmux.Ask(tmux.Own(), "show-environment", "-t", "="+name, ownerTag)
	owner, tagged := strings.CutPrefix(tag, ownerTag+"=")
	return err == nil && tagged && owner != ""
}

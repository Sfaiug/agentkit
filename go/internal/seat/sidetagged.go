package seat

import (
	"slices"
	"strings"

	"agentkit/internal/agent"
	"agentkit/internal/tmux"
)

// noSeat is whether none of those sessions on ak's own server, which neither ak's mark nor a
// record makes seats, is one (orch.seated): a session a seat started is that seat's, whatever runs
// in it, a harness included, so the process table is read only for the others, each a seat while
// an agent runs in it.
func noSeat(names ...string) bool {
	return agent.Agentless(tmux.Own(), slices.DeleteFunc(slices.Clone(names), sideSession))
}

// sideSession is whether a session neither ak opened nor a record names is one a seat started,
// which carries that seat's tag in its own environment: a format falls back to the server's, which
// holds the tag whenever a process in a tagged pane started the server, and an empty tag names no
// seat.  Only such a session is one maintenance may close (closeSideSessions).
func sideSession(name string) bool {
	tag, err := tmux.Ask(tmux.Own(), "show-environment", "-t", "="+name, ownerTag)
	owner, tagged := strings.CutPrefix(tag, ownerTag+"=")
	return err == nil && tagged && owner != ""
}

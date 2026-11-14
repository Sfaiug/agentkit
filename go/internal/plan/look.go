package plan

import (
	"path/filepath"
	"strings"
	"sync"

	"agentkit/internal/config"
)

// A Look is how plans are looked up: under the names a seat goes by, the one it has now and every
// name a rename pointer leads from to it.  The zero Look follows every pointer on disk at each
// lookup, as a writer under its lock must.  An open screen's frame takes one of its own (OneLook),
// as Python's config.session_aliases is held for a pass (look.once).
type Look struct{ held func() map[string][]string }

// OneLook is a frame's Look: every pointer followed at its first lookup and held for the rest of
// the frame, however many plans it looks up.  The next frame takes its own.
func OneLook() Look { return Look{sync.OnceValue(renamedInto)} }

// Names are the names a seat goes by: the one it has now, then every name renamed into it.
func (look Look) Names(current string) []string {
	into := renamedInto
	if look.held != nil {
		into = look.held
	}
	return append([]string{current}, into()[current]...)
}

// renamedInto is, by the name each leads to now, every name a rename pointer leads from, in name
// order: each session file listed once and followed through config.ResolveSession.
func renamedInto() map[string][]string {
	into := map[string][]string{}
	for _, record := range config.SeatFiles() {
		old := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(record), "session-"), ".json")
		if now, _, _ := config.ResolveSession(old); now != old {
			into[now] = append(into[now], old)
		}
	}
	return into
}

package seat

import (
	"slices"

	"agentkit/internal/run"
)

// wordStalls is whether all a seat's word reads of each of watch.json's `stalls` is that it is held
// (stallHeld) and whether its owner was asked (stallTold): a plain stall, or one watch.health keeps
// of a login out (`kind` "auth"), whose news the word reads off `auth_out` instead (loginOut).
func wordStalls(stalls *run.Object) bool {
	return !slices.ContainsFunc(stalls.Keys(), func(name string) bool {
		entry, ok := stalls.Get(name).(*run.Object)
		return !(ok && entry.Get("kind") == "auth") && !PlainStalls(run.Fields(name, stalls.Get(name)))
	})
}

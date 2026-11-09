package launch

import (
	"agentkit/internal/config"
	"agentkit/internal/machines"
)

// machined is whether a repository run's work may go to a machine Go sends none to, which leaves
// the run Python's: one ak may rent, or one that takes model turns.  The suite helper is Go's.
func machined() bool {
	return config.MayRent() || machines.TakesTurns()
}

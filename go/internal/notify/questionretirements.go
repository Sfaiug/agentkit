package notify

import "agentkit/internal/config"

// Python drains deferred question retirements under the seat lock. Until it
// does, neither a recorded question nor a chooser can be read as still standing.
func retirementsDrained() bool {
	return config.Listable(outbox()) && len(config.Glob(outbox(), "*.clear")) == 0
}

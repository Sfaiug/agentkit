package matrix

import (
	"fmt"

	"agentkit/internal/adapters"
	"agentkit/internal/pick"
	"agentkit/internal/worker"
)

func init() { adapters.Refused, worker.Refused = Refused, Refused }

// Refused is why no turn or seat is had on the configured model name while it is off (Off), in
// Python's matrix.refuse_off's words: every turn (worker.Turn) and every seat's command
// (adapters.Fresh, adapters.Resumed) ask it first, so no named, saved or configured model gets
// around the picks.
func Refused(name string) error {
	if off, err := Off(name); err != nil || !off {
		return err
	}
	return fmt.Errorf("%s is %s: turn it on with `companies` or `models_off` in config.toml", name, pick.OffList)
}

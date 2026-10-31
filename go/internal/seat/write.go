package seat

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Write puts a value into the seat's live-state record under the lock Python ak's writers take,
// as watch.seat_write merges one field.
func Write(name, key string, value any) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	state := filepath.Join(config.Home(), "state")
	return put(filepath.Join(state, "seat-"+name+".json"), filepath.Join(state, "seat-"+name+".lock"), run.Line, true, set([]field{{key, value}}, field{"session", name}))
}

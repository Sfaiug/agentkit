package seat

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// KeepsConfigEfforts is whether KeepConfigEfforts keeps every seat's record as Python's save
// does, settled before anything is written, since it writes the records one by one: the config
// bound as Python binds it, and no record holding what Python reads and Go cannot write back.
func KeepsConfigEfforts() bool {
	if _, err := config.Bind(); err != nil {
		return false
	}
	for _, path := range config.SeatRecords("session") {
		if _, err := run.ReadJSON(path); errors.Is(err, run.ErrLoneSurrogate) {
			return false
		}
	}
	return true
}

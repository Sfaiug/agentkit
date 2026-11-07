package harness

import (
	"encoding/json"

	"agentkit/internal/run"
)

// Launch is a typing receipt's `launch`, written while its harness names no conversation yet, as
// on a fresh launch: the record's LaunchKeys that hold a value, by which that harness names the one
// the line went into once it has (WentInto).
func Launch(record map[string]any) *run.Object {
	launch := run.NewObject()
	for _, key := range LaunchKeys {
		if record[key] != nil {
			data, _ := json.Marshal(record[key]) // as encoding/json read it from the record
			value, _ := run.Decode(data)
			launch.Set(key, value)
		}
	}
	return launch
}

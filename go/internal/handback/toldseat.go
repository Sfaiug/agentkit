package handback

import "agentkit/internal/run"

// ToldItsSeat is whether the run's own notice told its seat how it ended, as Python's wait_over
// reads the seat's wait on it: its line typed or printed by the seat's own look, or its change
// gone live said other than recorded.
func ToldItsSeat(record *run.Object) bool {
	note := record.Get("handback_note")
	return run.HandedBack(record) && (note == nil || note == looked) ||
		record.Truthy("live_notified") && record.Str("live_note") != routine
}

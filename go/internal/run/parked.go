package run

import (
	"errors"
	"time"
)

// Parked is whether any run of that seat sits parked undecided (stop._parked): ended unsettled or
// stalled, unacknowledged, and with no later merged run to replace it.  An error where a record
// Go cannot read as Python does, or an exhausted run whose wait it does not follow (`going`
// reads `exhausted_wait`), could say so.
func Parked(name string, now time.Time) (bool, error) {
	var records []*Object
	for _, dir := range Dirs() {
		record, err := Read(dir)
		if errors.Is(err, ErrLoneSurrogate) {
			return false, err
		}
		if record != nil {
			records = append(records, record)
		}
	}
	index := NewIndex(records)
	for _, record := range records {
		if !index.Unfinished(record) || Seat(record) != name {
			continue
		}
		state := record.Str("state")
		if state == "exhausted" {
			return false, errExhausted
		}
		if state == "stalled" || !Going(record, now) {
			return true, nil
		}
	}
	return false, nil
}

var errExhausted = errors.New("an exhausted run, which Python's exhausted_wait reads")

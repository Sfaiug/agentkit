package run

import (
	"errors"
	"time"
)

// Records is every run's readable record as it stands, the census what reads runs together reads
// (record.runs); an error where a record holds what Go cannot read as Python does.
func Records() ([]*Object, error) {
	var records []*Object
	for _, dir := range Dirs() {
		record, err := Read(dir)
		if errors.Is(err, ErrLoneSurrogate) {
			return nil, err
		}
		if record != nil {
			records = append(records, record)
		}
	}
	return records, nil
}

// Parked is whether any run of that seat among every run's records sits parked undecided
// (stop._parked): ended unsettled or stalled, unacknowledged, and with no later merged run to
// replace it.  An error where an exhausted run, whose wait Go does not follow (`going` reads
// `exhausted_wait`), could say so.
func Parked(name string, records []*Object, now time.Time) (bool, error) {
	index, seat := NewIndex(records), Seats()
	for _, record := range records {
		if !index.Unfinished(record) || seat(record) != name {
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

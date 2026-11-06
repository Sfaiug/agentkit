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
// replace it.
func Parked(name string, records []*Object, now time.Time) bool {
	index, seat := NewIndex(records), Seats()
	for _, record := range records {
		if !index.Unfinished(record) || seat(record) != name {
			continue
		}
		if record.Str("state") == "stalled" || !Going(record, now) {
			return true
		}
	}
	return false
}

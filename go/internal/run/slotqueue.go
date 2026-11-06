package run

import (
	"errors"
	"path/filepath"
)

// SlotQueue is the runs waiting for a slot, first in line first, as the last poll left them in
// runs/.slots.queue (Python's gate.slot_queue); none where no poll left one to read.  False where
// Python reads what Go cannot keep, as a seat's name can be.
func SlotQueue() ([]string, bool) {
	saved, err := ReadJSON(filepath.Join(Runs(), ".slots.queue"))
	if errors.Is(err, ErrLoneSurrogate) {
		return nil, false
	}
	if saved == nil {
		return nil, true
	}
	var queue []string
	for _, id := range saved.List("queue") {
		queue = append(queue, Text(id))
	}
	return queue, true
}

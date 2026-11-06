package run

import "path/filepath"

// SlotQueue is the runs waiting for a slot, first in line first, as the last poll left them in
// runs/.slots.queue (Python's gate.slot_queue); none where no poll left one to read.
func SlotQueue() []string {
	saved, _ := ReadJSON(filepath.Join(Runs(), ".slots.queue"))
	if saved == nil {
		return nil
	}
	var queue []string
	for _, id := range saved.List("queue") {
		queue = append(queue, Text(id))
	}
	return queue
}

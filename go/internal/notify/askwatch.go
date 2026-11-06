package notify

import "path/filepath"

// A tick's bookkeeping alone changes no seat's answer to an explicit new question. Login,
// stall and other outstanding work still leave that answer to Python.
func quietWatch() bool {
	watch, err := readObject(filepath.Join(state(), "watch.json"))
	if err != nil || watch == nil {
		return false
	}
	for _, key := range watch.Keys() {
		switch key {
		case "seen_at", "tick", "tick_completed_at", "boot_id", "boot_resume":
			continue
		}
		if watch.Truthy(key) {
			return false
		}
	}
	return true
}

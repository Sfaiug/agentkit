package harness

import "agentkit/internal/run"

// antigravityKnown is the conversation the record gives the seat, else the one this process learned
// its launch's own agy holds open, read with no claim lock: what the listing learned at its start.
func antigravityKnown(record *run.Object) string {
	learned.Lock()
	defer learned.Unlock()
	return antigravityOwns(record)
}

// antigravityOwns is antigravityKnown, its caller holding learned's lock.
func antigravityOwns(record *run.Object) string {
	if mine := antigravityMine(record); mine != "" {
		return mine
	}
	launch, _ := record.Get("antigravity_launch").(string)
	return learned.by[launch]
}

package handback

import "agentkit/internal/run"

// LiveOwedNow is Python's `live_owed and not rides`: the seat of the merged run that went live
// still has to hear it, now rather than on its next prompt, which a live follower stays for; from
// census as liveOwed reads it, and an error where Go cannot read it as Python does.
func LiveOwedNow(record *run.Object, census []*run.Object) (bool, error) {
	if !record.Truthy("live_at") {
		return false, nil
	}
	owed, rides, err := liveOwed(record, census)
	return owed && !rides, err
}

// CarriesLive is Python's carries_live: the merged run went live, and its ending, still to be
// said, says so in its one line (carries); from census as liveOwed reads it.
func CarriesLive(record *run.Object, census []*run.Object) (bool, error) {
	if !record.Truthy("live_at") {
		return false, nil
	}
	return carries(record, census)
}

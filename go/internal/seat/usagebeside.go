package seat

import (
	"fmt"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/run"
)

// outOfUsage is the wait the seat is out of usage on (watch._session_state's usage()): one ak
// resumes it from when its windows come back, unless it rests done unprompted.  A move that
// failed comes back on no wait, which moveFailed answers first.
func outOfUsage(facts climbing) (*run.Object, error) {
	wait, err := usage(facts)
	if wait == nil || !wait.Truthy("until") {
		return nil, err
	}
	record, _ := run.ReadJSON(filepath.Join(facts.state, "session-"+facts.name+".json"))
	if record == nil {
		record = run.NewObject()
	}
	if done, err := doneUnprompted(facts.name, facts.own, record, facts.file, facts.found, facts.runsOwe); done || err != nil {
		return nil, err
	}
	return wait, nil
}

// besideUsage is an answer only what the seat waits on gives it, unless it is out of usage: then
// nothing it waits on moves before its usage comes back, and its rung says so.
func (facts climbing) besideUsage(said *answer, err error) (*answer, error) {
	if said == nil || err != nil {
		return said, err
	}
	if wait, err := outOfUsage(facts); wait != nil || err != nil {
		return nil, err
	}
	return said, nil
}

// runsOwe is watch.runs_owe of the seat's own runs: one goes on by itself, is parked, sits
// undecided or is still the owner's to look at.
func (facts climbing) runsOwe() (bool, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return false, err
	}
	return slices.ContainsFunc(facts.mine, func(each ran) bool {
		return each.view != nil && (each.resumes() || each.view.parked || each.view.undecided || each.view.needs)
	}), nil
}

// newsOwed is what watch.news_owed reads where a look read the seat's screen (`authority`), as the
// reason ak types it: the end of its `ak wait` not yet told, or an ending of its own runs nobody
// has heard that is the seat's to decide, neither recorded without typing nor riding on its next
// prompt; "" for none.
func (facts climbing) newsOwed() string {
	if facts.found.authority == "" {
		return ""
	}
	if wait := facts.file.Dict("wait"); wait != nil && wait.Truthy("over") && !wait.Truthy("told") {
		return fmt.Sprintf("telling it its wait on %v is over", wait.Get("on"))
	}
	for _, each := range facts.mine {
		if !run.OwesEnding(each.record, time.Unix(0, int64(facts.now*1e9))) {
			continue
		}
		if recorded, pending := EndingDelivery(each.record, each.census, facts.name); !recorded && (!pending || each.record.Truthy("handback_typed")) {
			return fmt.Sprintf("telling it how run %s ended", each.name)
		}
	}
	return ""
}

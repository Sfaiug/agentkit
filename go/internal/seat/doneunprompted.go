package seat

import (
	"errors"
	"slices"

	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// doneUnprompted is watch.done_unprompted, off the seat's look: its plan is finished, and since
// the plan's last write nothing has prompted it, the owner has written nothing in its conversation,
// it owes no name and stands on no `ak wait`, its look shows no turn in flight and nothing asked,
// and no run of its own owes work (owes, watch.runs_owe).  ErrUnread where a conversation Go does
// not read, or owes, could say otherwise.
func doneUnprompted(name, own string, record, file *run.Object, found sight, owes func() (bool, error)) (bool, error) {
	if !mayRestDone(name) {
		return false, nil
	}
	done, err := plan.DoneAt(name)
	if err != nil || done.IsZero() {
		return false, ErrUnread
	}
	waits := false
	if wait := file.Dict("wait"); wait != nil {
		_, named := wait.Get("on").(string)
		waits = named && !wait.Truthy("over") && slices.Contains([]string{"pr", "run", "job"}, wait.Str("kind"))
	}
	flight, _ := found.turnInFlight(own)
	if waits || record.Truthy("unnamed") || flight || found.state == "asking" || found.hooked == "asking" {
		return false, nil
	}
	said, err := notify.OwnerSaid(name)
	if err != nil {
		return false, ErrUnread
	}
	if slices.ContainsFunc(said, func(at float64) bool { return at > seconds(done) }) {
		return false, nil
	}
	owed, err := owes()
	return !owed && err == nil, err
}

// ownRunsUnread is owes where nothing reads the seat's runs: any run of its own might owe work.
func ownRunsUnread(name string) func() (bool, error) {
	return func() (bool, error) {
		for _, dir := range run.Dirs() {
			if mine, err := run.Read(dir); errors.Is(err, run.ErrLoneSurrogate) || mine != nil && run.Seat(mine) == name {
				return false, ErrUnread
			}
		}
		return false, nil
	}
}

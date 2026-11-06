package seat

import (
	"slices"
	"strings"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Waits is each seat whose `ak wait` is not yet told, at the ended waits row's reading: every
// record, as watch.wait_over reads them, since a gone seat's ended wait still owes its line and a
// closed one's still ends on its fact.  False where one is a record the menu does not offer.
func (home Home) Waits() ([]Revival, bool) {
	var waits []Revival
	for _, each := range home.Revivals() {
		if untold(each.File) {
			waits = append(waits, each)
		}
	}
	for _, record := range home.records {
		if untold(revivalFile(record.Name)) && !slices.ContainsFunc(waits, func(each Revival) bool { return each.Name == record.Name }) {
			return nil, false
		}
	}
	return waits, true
}

func untold(file *run.Object) bool {
	wait := file.Dict("wait")
	if wait == nil {
		return false
	}
	_, named := wait.Get("on").(string)
	return named && !wait.Truthy("told")
}

// MarkWait is watch.wait_mark: marks put on the seat's wait under its lock, only while it is
// still the wait read, the same `on` and `at`; a newer `ak wait` or an `ak notify` meanwhile is
// left as the seat wrote it.  The wait as marked, nil where it was not that wait.
func MarkWait(name string, wait *run.Object, marks ...any) (*run.Object, error) {
	var marked *run.Object
	path := seatFile(name)
	err := put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(file *run.Object) bool {
		current := file.Dict("wait")
		if current == nil || !run.Equal(current.Get("on"), wait.Get("on")) || !run.Equal(current.Get("at"), wait.Get("at")) {
			return false
		}
		marked = run.SetAll(current.Copy(), marks...)
		return set([]field{{"wait", marked}}, field{"session", name})(file)
	})
	return marked, err
}

// WaitAlert is the event the owner is paged as where a gone seat could not be reopened once its
// wait ended (watch.wait_over's event_id).
func WaitAlert(name string, wait *run.Object) string {
	return "wait:" + name + ":" + run.Text(wait.Get("at"))
}

// waitsGone is a gone seat whose end cut nothing off (watch.cut_off), whose word is its standing
// wait's, or the owner's since the ended waits row could not reopen it once that wait ended:
// revive_seats leaves it be, for the ended waits row to reopen or for the owner.
func (seat Seat) waitsGone() bool {
	alert := notify.Last(seat.Name)
	paged := alert != nil && strings.HasPrefix(alert.Str("source"), "wait:"+seat.Name+":")
	return (seat.Word == "working" && Waiting(seat.Name) || paged) && seat.cutNothing()
}

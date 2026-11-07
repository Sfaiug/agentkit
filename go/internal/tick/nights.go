package tick

import (
	"os"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// nightEvery is how often a checkout's night is read, Python's nightly.EVERY.
const nightEvery = 3600

// noNights is whether no checkout's default branch declares a night read.
func noNights() bool { return noneDeclares("nightly") }

// nights is the night reads row where no checkout declares one (nightly.tick): each checkout's
// hourly read, which reads nothing, stamped in state/nightly.json. One the fetch just gave a
// night read stays unstamped, for the next tick to leave to Python.
func (t *ticking) nights() error {
	path := statePath("nightly.json")
	record := run.NewObject()
	if data, err := os.ReadFile(path); err == nil {
		if value, err := run.DecodeLimited(data); err == nil {
			if read, ok := value.(*run.Object); ok {
				record = read
			}
		}
	}
	// a number is the one stamp the version before kept: every checkout's, until it has its own
	before := record.Get("asked")
	asked, ok := before.(*run.Object)
	if !ok {
		asked = run.NewObject()
	}
	record.Set("asked", asked)
	checkouts, _ := seat.Checkouts()
	for i := len(checkouts) - 1; i >= 0; i-- {
		checkout, now, last := checkouts[i], epoch(t.clock()), before
		if asked.Has(checkout) {
			last = asked.Get(checkout)
		}
		if at, ok := run.Num(last); ok && 0 <= now-at && now-at < nightEvery || declares(checkout, "nightly") {
			continue
		}
		asked.Set(checkout, now)
		if err := replaceFile(path, run.Line(record)); err != nil {
			return err
		}
	}
	return nil
}

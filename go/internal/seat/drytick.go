package seat

import (
	"path/filepath"

	"agentkit/internal/run"
)

// DryTick has every look until end share one dry look (dryLook), so a dry tick's later rows read
// what its earlier ones would have saved, as a real tick's read what they saved: its notification
// retry reads the word its seat health row would publish.
func DryTick() (end func()) {
	drying = dryLook{}
	return func() { drying = nil }
}

// Drying is whether the look under way is a dry one, for a row's reading of the seat it looks at.
func Drying() bool { return drying != nil }

// savedStop is whether the seat file as saved passes what watch._stop_nudge asks of it: at its
// prompt, not interrupted, its stop dated.  Python's dry tick takes no look, so its nudge reads the
// saved file where this look reads what it found; the stop's words both read off the screen.
func (seat Seat) savedStop(state string) bool {
	saved, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if saved == nil {
		return false
	}
	_, dated := saved.Num("stop_said_at")
	return saved.Str("state") == "at_prompt" && !saved.Truthy("interrupted") && dated
}

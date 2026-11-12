package notify

import "agentkit/internal/run"

// undated is the moment a need no moment dates is carded from, as Python's transition takes it: the
// first sight of a seat dates its word by its rung, and a stalled run's record holds no finished_at.
// The card's episode of that word keeps the moment it began, and a new one begins now.
func undated(name string, clock func() float64) any {
	card, _ := readObject(seatFile("card", name, "json"))
	if card != nil && card.Str("word") == "needs you" {
		if at, dated := finite(card.Get("since")); dated {
			return run.Float(at)
		}
	}
	return run.Float(clock())
}

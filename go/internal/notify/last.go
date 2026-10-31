package notify

import "agentkit/internal/run"

// NeededSince is whether the seat's last notice is a question `ak notify needs` recorded at
// since or later, read from its file as the stop hook reads it (`told`).
func NeededSince(seat string, since float64) bool {
	notice, _ := run.ReadJSON(seatFile("notify", seat, "json"))
	if notice == nil {
		return false
	}
	at, dated := notice.Num("time")
	return notice.Get("kind") == "needs" && dated && at >= since
}

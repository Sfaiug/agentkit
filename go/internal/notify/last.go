package notify

import "agentkit/internal/run"

// NeededSince is the questions the seat's last notice asks where `ak notify needs` recorded it at
// since or later, read from its file as the stop hook reads it (`told`).
func NeededSince(seat string, since float64) []string {
	notice, _ := run.ReadJSON(seatFile("notify", seat, "json"))
	if notice == nil {
		return nil
	}
	if at, dated := notice.Num("time"); notice.Get("kind") != "needs" || !dated || at < since {
		return nil
	}
	return questions(notice)
}

package notify

import "agentkit/internal/run"

// Standing is whether a question of the seat's still stands (notify.last): what a message in its
// conversation may answer.
func Standing(seat string) bool {
	notice, _ := run.ReadJSON(seatFile("notify", seat, "json"))
	if notice == nil || notice.Get("kind") != "needs" || resolved(notice) {
		return false
	}
	_, asked := notice.Get("text").(string)
	return asked
}

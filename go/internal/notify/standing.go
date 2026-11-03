package notify

import "agentkit/internal/run"

// Standing is whether a question of the seat's still stands (notify.last): what a message in its
// conversation may answer.
func Standing(seat string) bool { return open(seat) != nil }

// open is the seat's notice while its question stands, nil otherwise.
func open(seat string) *run.Object {
	notice, _ := run.ReadJSON(seatFile("notify", seat, "json"))
	if notice == nil || notice.Get("kind") != "needs" || resolved(notice) {
		return nil
	}
	if _, asked := notice.Get("text").(string); !asked {
		return nil
	}
	return notice
}

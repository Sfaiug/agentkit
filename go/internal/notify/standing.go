package notify

import "agentkit/internal/run"

// Standing is whether a question of the seat's still stands (notify.last): what a message in its
// conversation may answer.
func Standing(seat string) bool { return Last(seat) != nil }

// Last is the seat's notice while it stands, nil otherwise (notify.last): every reader's, so only
// read it.  What changes it under its lock reads its own (open).
func Last(seat string) *run.Object { return stands(run.Shared(seatFile("notify", seat, "json"))) }

// open is Last read from the file into an object of the caller's own, to change under the notice's
// lock.
func open(seat string) *run.Object { return stands(run.ReadJSON(seatFile("notify", seat, "json"))) }

func stands(notice *run.Object, _ error) *run.Object {
	if notice == nil || notice.Get("kind") != "needs" || resolved(notice) {
		return nil
	}
	if _, asked := notice.Get("text").(string); !asked {
		return nil
	}
	return notice
}

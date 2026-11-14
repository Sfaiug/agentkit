package handback

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// tellLive types the line saying the merged run at dir went live alone into its seat, as Python's
// live_passed does under the run's delivery lock: at its quiet prompt, the line's receipt kept on
// the run (live_typed) and, once it is sent, the run marked told; a seat not at its prompt is told
// on a later tick.  A dry tick types nothing: it says what it would tell.
func tellLive(dir string, record *run.Object, at float64, say func(string), dry bool) error {
	id, session := filepath.Base(dir), run.Seat(record)
	if dry {
		say("would tell its launching seat: " + liveSentence(record, dir))
		return nil
	}
	// handback.live_line: the whole sentence, else a short one pointing to result.md, saved first
	line := seatNotice(record, dir, liveSentence(record, dir), "run "+id+" is live.", "Decide the next step.", true)
	if line == "" {
		return fmt.Errorf("run %s's live notice fits no typed line", id)
	}
	var unkept error
	if !seat.TypeAtPrompt(session, line, nil, func(typed *run.Object) error {
		// no Enter goes without its receipt, which alone holds a second copy back: the line stays
		// in the composer, a draft no later tick types past
		if !mark(dir, record, "live_typed", typed) {
			unkept = errUnrecorded
		}
		return unkept
	}, say) {
		return unkept
	}
	if !mark(dir, record, "live_notified", run.Float(at), "live_typed", nil) {
		return errUnrecorded
	}
	say(fmt.Sprintf("told the %s seat: %s", session, line))
	return nil
}

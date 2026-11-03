package plan

import (
	"os"
	"slices"
	"time"

	"agentkit/internal/config"
)

// Owes is whether the seat's plan owes work (stop.owed): an open line no run is on its way with
// (`taken`), or a plan nothing can read, which proves nothing done.  ErrUnread, owing, where only
// lines whose runs Go cannot read as Python does could owe.
func Owes(name string) (bool, error) {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return true, nil
	}
	lines, err := read(current)
	if err != nil {
		return true, nil
	}
	var unread error
	for _, line := range lines {
		if !open(line) {
			continue
		}
		written, ok := parse(line)
		if !ok || !written.Deferred {
			return true, nil
		}
		if taken, err := taken(current, written); err != nil {
			unread = err
		} else if !taken {
			return true, nil
		}
	}
	return unread != nil, unread
}

// LiveUnrecorded is whether the seat's own ssh reached the live host this turn (ReachedLive) and
// its plan has no open line to say what it did there, a run's deferred one included
// (stop.live_unrecorded); a plan nothing can read shows nothing missing from it.
func LiveUnrecorded(current string) bool {
	lines, err := read(current)
	return err == nil && !slices.ContainsFunc(lines, open) && ReachedLive(current)
}

// DoneAt is when the seat's finished plan (Finished) was last written, which ticked its last
// line, as stop.question_refused dates it: zero where it is not finished or nothing can date it,
// ErrUnread where Finished is.
func DoneAt(name string) (time.Time, error) {
	finished, err := Finished(name)
	if !finished {
		return time.Time{}, err
	}
	file, err := path(name)
	if err != nil {
		return time.Time{}, nil
	}
	info, err := os.Stat(file)
	if err != nil {
		return time.Time{}, nil
	}
	return info.ModTime(), nil
}

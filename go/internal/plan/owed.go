package plan

import (
	"iter"
	"os"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
)

// Owes is whether the seat's plan owes work (stop.owed): an open line no run is on its way with
// (`taken`), the done check a plan with every line done owes (checkOwed), or a plan nothing can
// read, which proves nothing done.  ErrUnread, owing, where only lines whose runs Go cannot read as
// Python does, or a check it cannot weigh, could owe.
func Owes(name string) (bool, error) { return owes(name, true) }

// OwesLine is Owes without the done check (stop.owed_line with `check` false): only the seat's own
// `ak plan` makes one, so a seat nobody is in owes nothing for it alone.
func OwesLine(name string) (bool, error) { return owes(name, false) }

func owes(name string, check bool) (bool, error) {
	var unread error
	for _, err := range owed(name, check) {
		if err == nil {
			return true, nil
		}
		unread = err
	}
	return unread != nil, unread
}

// OwedLine is the first line the seat owes, in its plan's own words, else the done check a plan
// with every line done owes (stop.owed_line): "" for a plan nothing can read, and owes false where
// it owes nothing.  ErrUnread, owing, where Go cannot weigh a line before it or the check.
func OwedLine(name string) (line string, owes bool, err error) {
	for line, err := range owed(name, true) {
		return line.What, true, err
	}
	return "", false, nil
}

// owed is each line the seat owes, its What in its plan's own words, in order, then, where check,
// the done check it owes: an empty one alone for a plan nothing can read, and an error for a line
// whose runs, or a check whose owner's words, Go cannot read as Python does.
func owed(name string, check bool) iter.Seq2[entry, error] {
	return func(yield func(entry, error) bool) {
		current, _, err := config.ResolveSession(name)
		var lines []string
		if err == nil {
			lines, err = read(current)
		}
		if err != nil {
			yield(entry{}, nil)
			return
		}
		for _, line := range lines {
			if !open(line) {
				continue
			}
			written, ok := parse(line)
			if ok && written.Deferred {
				if taken, err := taken(current, written, followupOpen); err != nil {
					if !yield(entry{}, err) {
						return
					}
					continue
				} else if taken {
					continue
				}
			}
			if !ok {
				line = strings.TrimFunc(line, config.Space)
				written.What = strings.TrimFunc(line[boxLine.FindStringIndex(line)[1]:], config.Space)
			}
			if !yield(written, nil) {
				return
			}
		}
		if !check {
			return
		}
		if owes, err := checkOwed(current, lines); owes || err != nil {
			yield(entry{What: owedCheck}, err)
		}
	}
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

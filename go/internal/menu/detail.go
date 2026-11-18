package menu

import (
	"slices"

	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// Task is a task's progress as the seat read it, independent of how its squares are drawn.
type Task = seat.Task

// detail is the lines under a seat's row (menu.detail): the text the owner left unsent, then,
// whatever its word, who builds and who reviews alone, never what it said nor a task's squares,
// which its row counts and its seat's bar draws.
func detail(s terminal.Screen, seat Seat, room int) []string {
	if seat.draft != nil {
		return nil // the draft's crew or refusal is part of its row block
	}
	var lines []string
	if seat.Unsent != "" {
		for _, line := range terminal.Wrap(s.Unsent(seat.Unsent), room) {
			lines = append(lines, s.Styled(line, "amber"))
		}
	}
	who := terminal.Crew(seat.Builds, seat.Reviews)
	if terminal.Cells(who) > room {
		who = terminal.CutSpaced(who, room)
	}
	if line := s.Styled(who, "muted"); terminal.Plain(line) != "" {
		lines = append(lines, line)
	}
	return lines
}

func keepDetail(lines []string, most, room int) []string {
	if most <= 0 {
		return nil
	}
	if len(lines) > most {
		lines = slices.Clone(lines[:most])
		lines[most-1] = terminal.Cut(lines[most-1]+" …", room)
	}
	return lines
}

package menu

import (
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/motion"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// Task is a task's progress as the seat read it, independent of how its squares are drawn.
type Task = seat.Task

func detail(s terminal.Screen, seat Seat, room int, clock *motion.Clock) []string {
	if seat.draft != nil {
		return nil // the draft's crew or refusal is part of its row block
	}
	var lines []string
	if seat.Unsent != "" {
		for _, line := range terminal.Wrap(unsentMark(s, seat.Unsent), room) {
			lines = append(lines, s.Styled(line, "amber"))
		}
	}
	said := ""
	if seat.Word != "working" {
		said = terminal.Plain(seat.Said)
	}
	if said != "" || seat.Word == "needs you" || seat.Word == "done" || seat.Word == "out of usage" {
		return append(lines, terminal.Wrap(said, room)...)
	}
	least := 0
	if len(seat.Tasks) > 0 {
		least = 3 + terminal.Cells(squares(s, seat.Tasks, 3, nil))
	}
	who := terminal.Crew(seat.Model, seat.Builds, seat.Reviews)
	if terminal.Cells(who) > room-least {
		who = terminal.CutSpaced(who, room-least)
	}
	line := s.Styled(who, "dim")
	left := room - terminal.Cells(who) - 3
	if len(seat.Tasks) > 0 && left >= least-3 {
		line += "   " + squares(s, seat.Tasks, left, clock)
	}
	if terminal.Plain(line) != "" {
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

func squares(s terminal.Screen, tasks []Task, room int, clock *motion.Clock) string {
	fit := len(tasks)
	for fit > 0 {
		size := 5*fit - 2
		if fit < len(tasks) {
			size += 3 + len(strconv.Itoa(len(tasks)-fit))
		}
		if size <= room {
			break
		}
		fit--
	}
	full, empty := "■", "□"
	if s.ASCII() {
		full, empty = "#", "-"
	}
	var parts []string
	for _, task := range tasks[:fit] {
		filled := strings.Repeat(full, task.Stage+1)
		if task.Moving {
			filled = clock.Breathing(s, filled, "working")
		} else {
			filled = s.Styled(filled, "dim")
		}
		parts = append(parts, filled+s.Styled(strings.Repeat(empty, 2-task.Stage), "dim"))
	}
	if fit < len(tasks) {
		parts = append(parts, s.Styled("+"+strconv.Itoa(len(tasks)-fit), "dim"))
	}
	return strings.Join(parts, "  ")
}

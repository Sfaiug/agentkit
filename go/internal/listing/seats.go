package listing

import (
	"strings"
	"time"

	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

var listHeaders = []string{"name", "project", "state", "tally", "orchestrator", "workers", "age"}

// Seats draws Python's orch.list_table, with each explanation beneath its own row.
func Seats(screen terminal.Screen, seats []seat.Seat, now time.Time, why bool) []string {
	if len(seats) == 0 {
		return []string{"no orchestrator session; `ak orch <name>` starts one"}
	}
	widths := make([]int, len(listHeaders))
	for i, head := range listHeaders {
		widths[i] = terminal.Cells(head)
	}
	rows := make([][]string, len(seats))
	for i, each := range seats {
		rows[i] = []string{each.Name, each.Project, screen.StateText(each.Word), each.Tally, each.Orchestrator, each.Workers,
			terminal.FormatAge(float64(now.UnixNano())/1e9 - each.Created)}
		for column, text := range rows[i] {
			if column != 5 {
				widths[column] = max(widths[column], terminal.Cells(text))
			}
		}
	}
	room := screen.ContentWidth() - 2*6
	for i, width := range widths {
		if i != 5 {
			room -= width
		}
	}
	if room < 12 {
		return narrowSeats(screen, seats, rows, widths, now, why)
	}
	wrapped := make([][]string, len(rows))
	for i, row := range rows {
		wrapped[i] = wrapWorkers(row[5], room)
		widths[5] = max(widths[5], terminal.Cells(wrapped[i][0]))
	}
	dim := []string{"dim", "dim", "dim", "dim", "dim", "dim", "dim"}
	lines := []string{screen.TableRow(listHeaders, widths, dim)}
	indent := strings.Repeat(" ", widths[0]+widths[1]+widths[2]+widths[3]+widths[4]+2*5)
	for i, row := range rows {
		row[5] = wrapped[i][0]
		lines = append(lines, screen.TableRow(row, widths, []string{"", "", seats[i].Word, "", "", "", "dim"})+note(seats[i]))
		for _, extra := range wrapped[i][1:] {
			lines = append(lines, indent+extra)
		}
		lines = append(lines, explanation(seats[i], now, why)...)
	}
	return lines
}

// note is what a row says after its columns: `legacy` for a seat on the person's own tmux server.
func note(each seat.Seat) string {
	if each.Legacy() {
		return "  legacy"
	}
	return ""
}

func explanation(each seat.Seat, now time.Time, why bool) []string {
	if !why {
		return nil
	}
	return append([]string{"  path: " + each.Path()}, each.Explanation(now)[1:]...)
}

func narrowSeats(screen terminal.Screen, seats []seat.Seat, rows [][]string, widths []int, now time.Time, why bool) []string {
	first := []int{widths[0], max(1, screen.ContentWidth()-widths[0]-2)}
	lines := []string{screen.TableRow(listHeaders[:2], first, []string{"dim", "dim"})}
	for i, row := range rows {
		project := terminal.Wrap(row[1], first[1])
		if len(project) == 0 {
			project = []string{""}
		}
		lines = append(lines, screen.TableRow([]string{row[0], project[0]}, first, nil))
		for _, extra := range project[1:] {
			lines = append(lines, strings.Repeat(" ", first[0]+2)+extra)
		}
		tail := []string{screen.StateCell(seats[i].Word), row[3], row[4], row[6]}
		if terminal.Cells("  "+strings.Join(tail, "  ")) <= screen.ContentWidth() {
			lines = append(lines, "  "+strings.Join(tail, "  "))
		} else {
			lines = append(lines, "  "+strings.Join(tail[:2], "  "), "  "+strings.Join(tail[2:], "  "))
		}
		for _, chunk := range wrapWorkers(row[5], max(1, screen.ContentWidth()-2)) {
			lines = append(lines, "  "+chunk)
		}
		if note := note(seats[i]); note != "" {
			lines = append(lines, note)
		}
		lines = append(lines, explanation(seats[i], now, why)...)
	}
	return lines
}

// wrapWorkers is a worker list in whole names: cut at commas where the room runs out, a
// continued chunk keeping its comma, budgeted a cell, unless its one name fills the room.
func wrapWorkers(workers string, room int) []string {
	if terminal.Cells(workers) <= room {
		return []string{workers}
	}
	var chunks []string
	current := ""
	for _, name := range strings.Split(workers, ",") {
		switch {
		case current == "":
			current = name
		case terminal.Cells(current+","+name+",") > room:
			if terminal.Cells(current) < room {
				current += ","
			}
			chunks, current = append(chunks, current), name
		default:
			current += "," + name
		}
	}
	return append(chunks, current)
}

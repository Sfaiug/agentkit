package cli

import (
	"fmt"
	"io"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func init() { commands["orch list"] = orchList }

var listHeaders = []string{"name", "project", "state", "tally", "orchestrator", "workers", "age"}

// orchList draws the seats Go knows, or with none says how to open one; then where the agents
// run. Without `--why` alone: explaining a seat is still Python's.
func orchList(args []string, out, errOut io.Writer) int {
	now := time.Now()
	home, known := seat.Read(now)
	screen := terminal.For(out)
	lines, fits := listTable(screen, home.Seats, now)
	if !known || !home.Seatless() && len(args) > 0 || len(home.Seats) > 0 && !fits {
		return notImplemented(errOut, "orch list")
	}
	if err := home.Announce(now); err != nil {
		fmt.Fprintf(errOut, "ak orch: %v\n", err)
		return 1
	}
	if len(home.Seats) == 0 {
		lines = []string{"no orchestrator session; `ak orch <name>` starts one"}
	}
	for _, line := range lines {
		fmt.Fprintln(out, line)
	}
	for _, line := range terminal.Wrap(host.SliceLine(), screen.ContentWidth()) {
		fmt.Fprintln(out, terminal.Dim(out, line))
	}
	for _, each := range home.Seats {
		if each.Warning != "" {
			fmt.Fprintln(errOut, "WARN "+each.Warning)
		}
	}
	return 0
}

// listTable is Python's orch.list_table: the header and each seat's row, its workers wrapped at
// commas under their column where they do not fit; false on a screen too narrow to set the
// seven columns side by side.
func listTable(screen terminal.Screen, seats []seat.Seat, now time.Time) ([]string, bool) {
	widths := make([]int, len(listHeaders))
	for i, head := range listHeaders {
		widths[i] = terminal.Cells(head)
	}
	rows := make([][]string, len(seats))
	for i, each := range seats {
		rows[i] = []string{each.Name, each.Project, screen.StateText(each.Word), each.Tally, each.Orchestrator, each.Workers,
			terminal.FormatAge(seconds(now) - each.Created)}
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
		return nil, false
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
		lines = append(lines, screen.TableRow(row, widths, []string{"", "", seats[i].Word, "", "", "", "dim"}))
		for _, extra := range wrapped[i][1:] {
			lines = append(lines, indent+extra)
		}
	}
	return lines, true
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

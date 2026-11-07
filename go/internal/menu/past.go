package menu

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/terminal"
)

// PastSeat is a stopped seat's row, dated by the owner's close rather than its launch.
type PastSeat struct {
	Seat
	Closed  float64
	Restart string
}

func pastWhen(closed float64, now time.Time) (day, clock string) {
	then := time.Unix(int64(closed), 0).In(now.Location())
	date := func(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }
	days := max(0, int(date(now).Sub(date(then)).Hours()/24))
	switch {
	case days > 6:
		return "earlier", then.Format("2 Jan")
	case days > 1:
		return "this week", then.Format("Mon 15:04")
	}
	return []string{"today", "yesterday"}[days], then.Format("15:04")
}

// DrawPast uses the menu's frame, table cells, pages, highlight and keys. Detail gets only the
// room left after the heading and whole row: long descriptions never scroll the header away.
func DrawPast(s terminal.Screen, past []PastSeat, h Highlight, now time.Time, columns, height int) Frame {
	keys := "↑↓←→ move   ⏎ reopen   x remove   esc back"
	if s.ASCII() {
		keys = "arrows move   enter reopen   x remove   esc back"
	}
	room := height - 5 - len(keyLine(s, keys, columns, pageMark(s, 98, 99, false, false)))
	if len(past) == 0 || room < 2 {
		return Frame{}
	}
	width := max(1, min(columns, 100))
	num, name, project, clock, count := len(strconv.Itoa(len(past))), 1, 0, 0, 7
	f := Frame{width: columns, height: height, cursor: h.Cursor, hidden: h.Hidden}
	for _, each := range past {
		_, when := pastWhen(each.Closed, now)
		name = max(name, terminal.Cells(each.Name))
		project = max(project, terminal.Cells(base(each.Checkout)))
		clock = max(clock, terminal.Cells(when))
		if each.Total > 0 {
			count = max(count, len(fmt.Sprintf("%d of %d", each.Done, each.Total)))
		}
		f.order = append(f.order, each.Name)
	}
	if !slices.Contains(f.order, f.cursor) {
		f.cursor = f.order[0]
	}
	name, project = min(name, 24, max(1, width-2-num-2)), min(project, max(1, width-4))
	free := width - (2 + num + 2 + name + 2 + project + 6 + clock) // a row stops two short, as Python's
	fold := width < 60 || free < count
	indent := strings.Repeat(" ", 2+num+2)
	details := map[string][]string{}
	var groups []pageProject
	most, opened := 0, 0
	for i, each := range past {
		day, when := pastWhen(each.Closed, now)
		bar := s.Styled("no plan", "dim")
		if each.Total > 0 {
			seat := each.Seat
			seat.Word, seat.moved = "idle", 1
			if seat.Done == seat.Total {
				seat.Word = "done"
			}
			bar = planBar(s, seat, map[bool]int{true: 0, false: free}[fold], 0)
		}
		number := strconv.Itoa(i + 1)
		head := "  " + strings.Repeat(" ", num-len(number)) + s.Styled(number, "dim") + "  " + terminal.Pad(each.Name, name)
		var block []row
		if fold {
			block = append(block, row{strings.TrimRight(head, " "), each.Name})
			tail := strings.TrimSpace(base(each.Checkout) + "  " + bar + "  " + when)
			for _, line := range terminal.Wrap(tail, max(1, width-4)) {
				block = append(block, row{"    " + line, each.Name})
			}
		} else {
			line := head + "  " + cell(s, base(each.Checkout), project, "dim") + "  " + bar +
				strings.Repeat(" ", max(0, free-terminal.Cells(bar))) + "  " + strings.Repeat(" ", clock-terminal.Cells(when)) + when
			block = []row{{strings.TrimRight(line, " "), each.Name}}
		}
		if len(block)+1 > room {
			return Frame{}
		}
		if len(groups) == 0 || terminal.Plain(groups[len(groups)-1].heading.line) != day {
			groups = append(groups, pageProject{heading: row{line: s.Bold(day)}})
		}
		groups[len(groups)-1].blocks = append(groups[len(groups)-1].blocks, block)
		lines := terminal.Wrap(each.Said, max(1, width-len(indent)))
		for _, line := range terminal.Wrap(each.Restart, max(1, width-len(indent))) {
			lines = append(lines, s.Styled(line, "dim"))
		}
		details[each.Name] = lines
		most, opened = max(most, len(block)), max(opened, len(lines))
	}
	opened = min(opened, height/2, max(0, room-most-1))
	opens := map[string]int{}
	if !h.Hidden {
		for name, lines := range details {
			opens[name] = min(opened, len(lines))
		}
	}
	pages := projectPages(groups, room, false, opens)
	f.page = max(0, slices.IndexFunc(pages, func(lines []row) bool {
		return slices.ContainsFunc(lines, func(each row) bool { return each.seat == f.cursor })
	}))
	f.turns = pageTurns(pages)
	mark := ""
	if len(pages) > 1 {
		mark = pageMark(s, f.page, len(pages), false, false)
	}
	panel := Panel(s, "past sessions", now.Format("15:04"), nil, keys)
	f.Lines, f.spots = panel[:2:2], make([]string, 2)
	body := pages[f.page]
	for i, each := range body {
		line := each.line
		lit := !h.Hidden && each.seat != "" && each.seat == f.cursor
		if lit {
			line = s.Highlight(line, i == 0 || body[i-1].seat != each.seat)
		}
		f.Lines, f.spots = append(f.Lines, line), append(f.spots, each.seat)
		if lit && (i+1 == len(body) || body[i+1].seat != each.seat) {
			for _, line := range keepDetail(details[each.seat], opens[each.seat], width-len(indent)) {
				f.Lines = append(f.Lines, s.Highlight(indent+line, false))
				f.spots = append(f.spots, each.seat)
			}
		}
	}
	f.Lines = append(append(f.Lines, ""), keyLine(s, keys, columns, mark)...)
	return f
}

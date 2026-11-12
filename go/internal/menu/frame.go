package menu

import (
	"cmp"
	"math"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

const (
	least     = 3  // rows a page keeps; the usage block folds before it holds fewer
	opensAll  = 4  // lines a page keeps for what a row opens before the usage folds
	meterSize = 10 // cells of a subscription's meter
	cellSize  = 33 // ... and of its whole cell
	unfiled   = "not assigned yet"
	noSeat    = "  no sessions; n starts one"
	noPlan    = "no plan yet"
)

// A Seat is one row of the screen: its place in the whole list, what it is, and what opens under it.
type Seat struct {
	Number                                    int
	Name, Checkout, Model, Word, Unsent, Said string // Checkout "" is filed under none
	Alone                                     string // its model without the effort Model names
	Done, Total                               int    // its plan's lines done, of how many; none without one
	Builds, Reviews                           []string
	Tasks                                     []Task
	draft                                     *Draft

	// where it moves this frame (moving): its mark as drawn now, "" where it holds still, and its
	// line moved (0 to 1) from the share it stood at, its count from counted, its head lit
	mark        string
	from, moved float64
	counted     int
	lit         bool
}

// A Cell is a subscription on the grid: Left is 1 to 100 with a meter, 0 for credits, -1 for none;
// Ends is what is said of a login about to end, its meter amber meanwhile.  The rest is what
// Subscriptions says of it: its provider and account ("" for a provider's one login), the company
// it sits under and that company's colour, the harness that signs it in, the resets it holds and
// whose login it is; Notes, what the line under the grid says of its reading while pointed at.
type Cell struct {
	Label, Said, Ends                           string
	Left                                        int
	Provider, Account, Company, Colour, Harness string
	Held, Email, Plan                           string
	Notes                                       []usage.Note
}

// A View is everything the frame is drawn from.
type View struct {
	Screen      terminal.Screen
	Seats       []Seat
	Cells       []Cell
	Clock, Keys string
	Standing    string // what stands under the usage: a worker token that ends soon
	Highlight   Highlight
	New         *Draft
	Motion      *motion.Clock  // where what moves is this frame; nil, all still
	Switches    map[string]int // each project naming its feature switches, by checkout: how many are hidden
}

// Keys is the main screen's key line, `p past` on it while a seat the owner stopped is offered.
func Keys(screen terminal.Screen, past bool) string {
	line := "↑↓←→ move   ⏎ open   "
	if screen.ASCII() {
		line = "arrows move   enter open   "
	}
	line += "n new   "
	if past {
		line += "p past   "
	}
	return line + "c config   esc leave"
}

// A row is a screen line and the seat it draws, "" for a line of no seat.
type row struct{ line, seat string }

// widths are the seat rows' columns, sized once per draw from every row on screen.
type widths struct {
	room, num, name, orch, count, free int
	narrow, under                      bool
}

// Lines is the frame, the height kept to but for two rows every draw leaves: the header and one dim
// rule, the usage grid, the line under it, the projects and their seats, and the key line, always
// last.  What does not fit folds as docs/cli-design.md says: the usage to its readings and then, with
// the frame's blank lines, away; a row's last column under it; more seats than fit, to pages, with
// the arrow toward a seat that needs the owner in amber.
func Lines(view View, width, height int) []string {
	return Draw(view, width, height).Lines
}

// Draw lays out the frame and the places navigation can reach on it together. A nonpositive
// height lists every row without filling a screen.
func Draw(view View, width, height int) Frame {
	bounded := height > 0
	if !bounded {
		height = math.MaxInt
	}
	view = view.withNew()
	s := view.Screen
	view.Seats = moving(s, view.Seats, view.Motion)
	layout := max(1, min(width, 120))
	projects := projects(view.Seats)
	sized := columns(s, view.Seats, width)
	full := usageLines(s, view.Cells, layout)
	summary := usageSummary(view.Cells, layout, -1)
	single := len(keyLine(s, view.Keys, width, ""))
	paging := len(keyLine(s, view.Keys, width, pageMark(s, 98, 99, false, false)))

	cursor := Step(view.Seats, view.Switches, view.Highlight.Cursor, 0)
	frame := Frame{cursor: cursor, hidden: view.Highlight.Hidden, width: width, height: height, order: seatOrder(view.Seats, view.Switches)}
	saidRoom := max(1, sized.room-(2+sized.num+2))
	said := map[string]int{}
	opens := 0
	for _, seat := range view.Seats {
		said[seat.Name] = len(detail(s, seat, saidRoom, nil))
		opens = max(opens, said[seat.Name])
	}
	opens = min(opens, max(1, height/2))

	standing := ""
	if view.Standing != "" {
		tone := "dim"
		if strings.Contains(view.Standing, "expired") {
			tone = "amber"
		}
		standing = "  " + s.Styled(terminal.Cut(view.Standing, layout-2), tone)
	}
	spare := func(meters []string, paged, compact bool, open int) int {
		keys := single + open
		if paged {
			keys = paging + open
		}
		if compact {
			extra := 0
			if standing != "" {
				extra = 1
			}
			return height - 2 - (keys + len(meters) + extra)
		}
		return height - 2 - (2 + len(meters) + 2 + 1 + keys)
	}
	keep := least
	if width < 60 {
		keep = 2 * least
	}
	block := full
	if len(block) == 0 {
		block = summary
	}
	meters, compact, grid := summary, true, false
	if spare(block, true, false, opensAll) >= keep {
		meters, compact, grid = block, false, len(full) > 0
	} else if spare(summary, true, false, opensAll) >= keep {
		compact = false
	} else {
		if left := spare(meters, true, true, 0) - 3; left < 0 && len(meters) > 1 {
			meters = usageSummary(view.Cells, layout, max(1, len(meters)+left))
		}
		meters = meters[:min(len(meters), max(0, len(meters)+spare(meters, true, true, 0)-1))]
	}

	blocks := func(most int) [][][]row {
		var all [][][]row
		for _, project := range projects {
			all = append(all, seatBlocks(s, project.seats, sized, most))
		}
		return all
	}
	own := blocks(-1)
	var flat []row
	for i, project := range projects {
		if i > 0 {
			flat = append(flat, row{})
		}
		flat = append(flat, headingRow(s, project, width, view.Switches))
		for _, block := range own[i] {
			flat = append(flat, block...)
		}
	}
	empty := len(flat) == 0
	if empty {
		flat = []row{{line: noSeat}}
	}

	paged := len(flat) > 1 && len(flat) > spare(meters, false, compact, opens)
	room := spare(meters, paged, compact, opens)
	need := 0
	for _, blocks := range own {
		for _, block := range blocks {
			need = max(need, len(block))
		}
	}
	need = 1 + min(2, need)
	if compact || !paged {
		opens = max(0, opens-max(0, need-room))
	} else {
		opens = max(0, opens-max(0, least-room))
	}
	paged = paged && len(flat) > spare(meters, false, compact, opens)
	room = max(1, spare(meters, paged, compact, opens))
	pages := [][]row{flat}
	if paged {
		kept := map[string]int{}
		for name, count := range said {
			kept[name] = min(count, opens)
		}
		var cut []pageProject
		for i, blocks := range blocks(room - 1) {
			cut = append(cut, pageProject{headingRow(s, projects[i], width, view.Switches), blocks})
		}
		pages = projectPages(cut, room+opens, true, kept)
	}
	page := max(0, slices.IndexFunc(pages, func(lines []row) bool {
		return slices.ContainsFunc(lines, func(each row) bool { return each.seat == cursor && cursor != "" })
	}))
	frame.page, frame.turns = page, pageTurns(pages)
	keys := keyLine(s, view.Keys, width, "")
	if len(pages) > 1 {
		needs := func(lines []row) bool { return needing(view.Seats, lines) }
		keys = keyLine(s, view.Keys, width, pageMark(s, page, len(pages),
			slices.ContainsFunc(pages[:page], needs), slices.ContainsFunc(pages[page+1:], needs)))
	}

	var out []string
	if !compact {
		out = append(out, headerLine(view.Clock, layout), s.Styled(strings.Repeat("─", layout), "dim"))
	}
	if grid {
		per := usageColumns(layout)
		for at := range view.Cells {
			n := at % per
			first, last := terminal.Drawn(meters[at/per], 3+n*(cellSize+2), 2+n*(cellSize+2)+cellSize)
			frame.meters = append(frame.meters, meterSpot{len(out) + 1 + at/per, first, last, at})
		}
		// the one the pointer is on in its colour, and what its cell has no room for under the grid
		if pointed := frame.meterAt(view.Highlight.Pointer); pointed >= 0 {
			meters = meterLines(s, view.Cells, layout, per, pointed, nil)
			standing = "  " + usageDetail(s, view.Cells[pointed], layout)
		}
	}
	out = append(out, meters...)
	if !compact {
		out = append(out, standing, "")
	} else if standing != "" {
		out = append(out, standing)
	}
	body := flat
	if !empty {
		body = pages[page]
	}
	above := ""
	frame.spots = make([]string, len(out))
	for at, each := range body {
		lit := !view.Highlight.Hidden && each.seat != "" && each.seat == cursor
		_, heading := view.Switches[each.seat]
		line := each.line
		if lit && heading {
			line = "  " + line // flush left: its mark goes in front of it
		}
		if lit {
			line = s.Highlight(line, each.seat != above)
		}
		out = append(out, line)
		frame.spots = append(frame.spots, each.seat)
		if lit && !heading && view.Highlight.Open && (at+1 == len(body) || body[at+1].seat != each.seat) {
			seat := view.Seats[slices.IndexFunc(view.Seats, func(seat Seat) bool { return seat.Name == each.seat })]
			for _, line := range keepDetail(detail(s, seat, saidRoom, view.Motion), opens, saidRoom) {
				out = append(out, strings.Repeat(" ", 2+sized.num+2)+line)
				frame.spots = append(frame.spots, each.seat)
			}
		}
		above = each.seat
	}
	if !compact {
		out = append(out, "")
	}
	for bounded && len(out) < height-2-len(keys) {
		out = append(out, "")
	}
	frame.Lines = append(out, keys...)
	return frame
}

// A project is a heading and the seats filed under it, each project where its first seat is.
type project struct {
	name  string
	filed bool
	seats []Seat
}

func grouped(seats []Seat) []project {
	var found []project
	for _, seat := range seats {
		at := slices.IndexFunc(found, func(each project) bool {
			return each.filed == (seat.Checkout != "") && (!each.filed || each.name == seat.Checkout)
		})
		if at < 0 {
			found = append(found, project{name: seat.Checkout, filed: seat.Checkout != ""})
			at = len(found) - 1
		}
		found[at].seats = append(found[at].seats, seat)
	}
	return found
}

// base is a checkout's last path element.
func base(path string) string { return path[strings.LastIndexByte(path, '/')+1:] }

// headerLine is `agentkit` at the left and the clock at the right; the title gives way, never the
// clock.
func headerLine(clock string, room int) string {
	return panelHeader("", clock, room)
}

// keyLine is the key line: each key dim, its word plain, wrapped to the layout; first, drawn as it
// is, the item in front of them.
func keyLine(s terminal.Screen, text string, width int, first string) []string {
	room := max(1, min(width, 120)) - 2
	var pieces []string
	if first != "" {
		pieces = append(pieces, first)
	}
	for _, phrase := range strings.Split(text, "   ") {
		key, word, _ := strings.Cut(strings.TrimSpace(phrase), " ")
		piece := s.Styled(key, "dim")
		if word = strings.TrimSpace(word); word != "" {
			piece += " " + word
		}
		pieces = append(pieces, piece)
	}
	var lines []string
	line := ""
	for _, piece := range pieces {
		switch {
		case line == "":
			line = piece
		case terminal.Cells(line+"   "+piece) > room:
			lines = append(lines, "  "+line)
			line = piece
		default:
			line += "   " + piece
		}
	}
	return append(lines, "  "+line)
}

// pageMark is where the owner is, `←  2 / 3  →`, each arrow amber where a seat that needs the owner
// is that way.
func pageMark(s terminal.Screen, page, pages int, back, on bool) string {
	arrow, ahead := "←", "→"
	if s.ASCII() {
		arrow, ahead = "<", ">"
	}
	tone := map[bool]string{false: "dim", true: "amber"}
	return s.Styled(arrow, tone[back]) + "  " + strconv.Itoa(page+1) + " / " + strconv.Itoa(pages) + "  " + s.Styled(ahead, tone[on])
}

func needing(seats []Seat, lines []row) bool {
	return slices.ContainsFunc(lines, func(each row) bool {
		return slices.ContainsFunc(seats, func(seat Seat) bool { return seat.Name == each.seat && seat.Word == "needs you" })
	})
}

func unsentMark(s terminal.Screen, text string) string {
	if s.ASCII() {
		return "* " + text
	}
	return "✎ " + text
}

// lastColumn is a row's one last column in room cells (menu.last_column), none where room is
// negative saying the fewest cells that hold it: its progress (planBar, barred), and `✎ unsent` two
// cells after where the owner left text.  The line keeps eight cells at least, unless narrow, where
// it takes the room and never more: the count alone where no cell of line fits, the mark alone where
// both do not.
func lastColumn(s terminal.Screen, seat Seat, room int, narrow bool) string {
	mark := ""
	if seat.Unsent != "" {
		mark = unsentMark(s, "unsent")
	}
	left := max(room, 0)
	if mark != "" {
		left -= terminal.Cells(mark) + 2
	}
	bar, text := "", ""
	if barred(seat) {
		smallest := 8
		if narrow {
			smallest = 0
		}
		bar = planBar(s, seat, left, smallest)
		text = terminal.Plain(planBar(s, seat, left, 0))
	}
	if narrow && mark != "" && room >= 0 && terminal.Cells(text) > left {
		bar = ""
	}
	switch {
	case mark == "":
		return bar
	case bar == "":
		return s.Styled(mark, "amber")
	}
	return bar + "  " + s.Styled(mark, "amber")
}

// columns sizes the rows' fixed columns: number, name, model and state, and the room their last one
// has.  Where even the narrowest do not fit the state goes under the row; the longer of name and
// model gives way first; and every row's last column stands beside it or, on a phone or where that
// room would not hold some row's, under it.
func columns(s terminal.Screen, seats []Seat, width int) widths {
	room := max(1, min(width, 100))
	num, name, orch, count := 1, 1, 0, 1
	for _, seat := range seats {
		num = max(num, terminal.Cells(strconv.Itoa(seat.Number)))
		name = max(name, terminal.Cells(seat.Name))
		orch = max(orch, terminal.Cells(seat.Model))
		count = max(count, terminal.Cells(s.StateText(seat.Word)))
	}
	num, name = min(num, 4), min(name, 24)
	state := 2 + count
	if 2+num+2+min(name, 8)+2+min(orch, 8)+state > room {
		count, state = 0, 0
	}
	// an effort gives way, whole, before any name is cut (orchestrator)
	fits := room - (2 + num + 2 + name + 2 + state)
	orch = 0
	for _, seat := range seats {
		orch = max(orch, terminal.Cells(seat.orchestrator(fits)))
	}
	for 2+num+2+name+2+orch+state > room && max(name, orch) > 1 {
		if name >= orch {
			name--
		} else {
			orch--
		}
	}
	fixed := 2 + num + 2 + name + 2 + orch + state + 2
	smallest := 10
	for _, seat := range seats {
		smallest = max(smallest, terminal.Cells(lastColumn(s, seat, -1, true)))
	}
	return widths{room: room, narrow: width < 60, num: num, name: name, orch: orch, count: count, free: room - fixed,
		under: width < 60 || room-fixed < smallest}
}

// orchestrator is what its model column says in `room` cells: its model at its effort where that
// fits, else the model alone, which the column may cut.
func (seat Seat) orchestrator(room int) string {
	if terminal.Cells(seat.Model) <= room || seat.Alone == "" {
		return seat.Model
	}
	return seat.Alone
}

// head is a row's fixed columns, its number kept behind the indent the highlight takes where even
// their narrowest do not fit.
func head(s terminal.Screen, seat Seat, w widths) string {
	number := terminal.Cut(strconv.Itoa(seat.Number), w.num)
	number = "  " + strings.Repeat(" ", max(0, w.num-terminal.Cells(number))) + s.Styled(number, "dim")
	rest := []string{terminal.Pad(seat.Name, w.name), cell(s, seat.orchestrator(w.orch), w.orch, "dim")}
	if w.count > 0 {
		text := terminal.Cut(s.StateText(seat.Word), w.count)
		rest = append(rest, state(s, seat, text)+strings.Repeat(" ", w.count-terminal.Cells(text)))
	}
	line := strings.Join(append([]string{number}, rest...), "  ")
	if terminal.Cells(line) <= w.room {
		return line
	}
	if left := w.room - terminal.Cells(number) - 2; left > 0 {
		return number + "  " + terminal.Cut(strings.Join(rest, " "), left)
	}
	return number
}

// tone is the colour a state word is drawn in.
func tone(word string) string {
	if word == "idle" {
		return "dim"
	}
	return word
}

// state is a seat's state text, or a piece of it, in its word's colour, its mark as the clock draws
// it this frame (moving).
func state(s terminal.Screen, seat Seat, text string) string {
	if rest, marked := strings.CutPrefix(text, s.Glyph(seat.Word)); marked && seat.mark != "" {
		return seat.mark + s.Styled(rest, tone(seat.Word))
	}
	return s.Styled(text, tone(seat.Word))
}

// cell is text cut, then styled, then padded, so the pads land outside the escapes.
func cell(s terminal.Screen, text string, room int, kind string) string {
	text = terminal.Cut(text, room)
	return s.Styled(text, kind) + strings.Repeat(" ", max(0, room-terminal.Cells(text)))
}

// seatBlocks is one block of lines per seat, no line keeping trailing space: its row, what stands
// under it, and a block of more than most lines (none where negative) cut to them, ending in `…`.
func seatBlocks(s terminal.Screen, seats []Seat, w widths, most int) [][]row {
	var blocks [][]row
	for _, seat := range seats {
		if seat.draft != nil {
			blocks = append(blocks, seat.draft.block(s, seat, w))
			continue
		}
		line := head(s, seat, w)
		last := ""
		if !w.under {
			last = lastColumn(s, seat, w.free, true)
		}
		var lines []string
		if last != "" {
			lines = []string{line + "  " + last}
		} else {
			lines = []string{line}
			room := max(1, w.room-4)
			if under := lastColumn(s, seat, room, w.narrow); under != "" {
				if terminal.Cells(under) > room {
					under = terminal.Cut(under, room)
				}
				lines = append(lines, "    "+under)
			}
		}
		if w.count == 0 {
			var under []string
			for _, each := range terminal.Wrap(s.StateText(seat.Word), w.room-4) {
				under = append(under, "    "+state(s, seat, each))
			}
			lines = slices.Insert(lines, 1, under...)
		}
		if most >= 0 && len(lines) > max(1, most) {
			keep := max(1, most)
			indent := strings.Repeat(" ", 2+w.num+2)
			if keep == 1 {
				lines = lines[:1]
			} else {
				var rest []string
				for _, each := range lines[keep-1:] {
					rest = append(rest, terminal.Plain(each))
				}
				lines = append(lines[:keep-1:keep-1], indent+terminal.Cut(strings.Join(rest, " "), w.room-len(indent)))
			}
		}
		block := make([]row, len(lines))
		for i, each := range lines {
			block[i] = row{strings.TrimRight(each, " "), seat.Name}
		}
		blocks = append(blocks, block)
	}
	return blocks
}

type pageProject struct {
	heading row
	blocks  [][]row
}

// projectPages packs seat blocks whole under their heading, in pages of room lines, the main
// screen's and the past screen's alike: a blank line between two headings on a page where apart, as
// on the screen that holds the projects.  A page keeps free the most lines a seat on it opens.  A
// block taller than a page under its heading is split, so tiny screens still fit.
func projectPages(projects []pageProject, room int, apart bool, opens map[string]int) [][]row {
	var pages [][]row
	var current []row
	currentHead, kept := -1, 0
	for at, each := range projects {
		for _, block := range each.blocks {
			need := block
			if len(current) == 0 || currentHead != at {
				need = []row{}
				if len(current) > 0 && apart {
					need = append(need, row{})
				}
				need = append(append(need, each.heading), block...)
			}
			own := opens[block[0].seat]
			if len(current) > 0 && len(current)+len(need)+max(kept, own) > room {
				pages = append(pages, current)
				current, currentHead, kept = nil, -1, 0
				need = append([]row{each.heading}, block...)
			}
			if len(need) > room {
				pages = append(pages, []row{each.heading})
				for i := 0; i < len(block); i += room {
					pages = append(pages, block[i:min(i+room, len(block))])
				}
				currentHead = at
				continue
			}
			current = append(current, need...)
			currentHead, kept = at, max(kept, own)
		}
	}
	if len(current) > 0 {
		pages = append(pages, current)
	}
	return pages
}

// usageLines is the cached weekly allowances as a grid: as many cells to a line as fit, each its
// label, a meter (terminal.ShareParts, full for what is left) and what it says.  What a cell says
// is whole: the labels give way to the longest, and a width with no room for a label beside it has
// no grid.
func usageLines(s terminal.Screen, cells []Cell, width int) []string {
	return meterLines(s, cells, width, usageColumns(width), -1, nil)
}

// usageColumns is how many cells a line of the grid holds in width: one to three, two apart.
func usageColumns(width int) int { return max(1, min(3, width/(cellSize+2))) }

// meterLines is usageLines per cell to a line, cell lit (from 0; -1 for none) with its label and
// what its meter has left in its company's colour and its login's amber left to the line under it,
// and took, where given, handed each cell's text that takes that colour: its cell, its column from
// 1, the text and what it is drawn in at rest, "" for plain.
func meterLines(s terminal.Screen, cells []Cell, width, per, lit int, took func(cell, column int, text, rest string)) []string {
	if len(cells) == 0 {
		return nil
	}
	if took == nil {
		took = func(int, int, string, string) {}
	}
	room := min(cellSize, width-2)
	saidRoom, labelWide := 0, 0
	cells = slices.Clone(cells)
	for i, each := range cells {
		cells[i].Said = terminal.Plain(each.Said)
		each.Said = cells[i].Said
		extra := 0
		if each.Left > 0 {
			extra = 6
		}
		saidRoom = max(saidRoom, terminal.Cells(each.Said)+extra)
		labelWide = max(labelWide, terminal.Cells(terminal.Plain(each.Label)))
	}
	labelRoom := min(12, room-2-saidRoom, labelWide)
	if labelRoom < 1 {
		return nil
	}
	meter := max(4, min(meterSize, room-labelRoom-13))
	var lines []string
	for start := 0; start < len(cells); start += per {
		var parts []string
		for n, each := range cells[start:min(start+per, len(cells))] {
			ink, rest, column := "", "", 3+n*(cellSize+2)
			if start+n == lit {
				ink = each.Colour
			}
			if each.Ends != "" {
				rest = "amber"
			}
			shown := terminal.Cut(each.Label, labelRoom)
			took(start+n, column, shown, "")
			text := shown + strings.Repeat(" ", labelRoom-terminal.Cells(shown)+2)
			if ink != "" {
				text = s.Styled(shown, ink) + text[len(shown):]
			}
			if each.Left <= 0 {
				switch {
				case each.Ends != "" && ink == "":
					text += s.Styled(each.Said, "amber")
				case each.Left < 0:
					text += s.Styled(each.Said, "dim")
				default:
					text += each.Said
				}
			} else {
				bar, empty := s.ShareParts(float64(each.Left)/100, meter)
				took(start+n, column+labelRoom+2, bar, rest)
				if fill := cmp.Or(ink, rest); fill != "" {
					bar = s.Styled(bar, fill)
				}
				text += bar + s.Styled(empty, "dim") + "  " + each.Said
			}
			parts = append(parts, text+strings.Repeat(" ", max(0, room-terminal.Cells(text))))
		}
		lines = append(lines, strings.TrimRight("  "+strings.Join(parts, "  "), " "))
	}
	return lines
}

// usageSummary is the usage folded: each subscription's label and what it has left, whole, as many
// to a line as fit; in most lines (any where negative), the last ending in ` · …` where readings are
// left out.
func usageSummary(cells []Cell, width, most int) []string {
	fill := func(found []Cell, room int) [][]string {
		lines := [][]string{{}}
		for _, each := range found {
			figure := "0%"
			switch {
			case each.Left > 0:
				figure = strconv.Itoa(each.Left) + "%"
			case each.Left == 0 && terminal.Cells(each.Said) <= room:
				figure = each.Said
			case strings.HasPrefix(each.Said, "—"):
				figure = "—"
			}
			part := figure
			if spare := room - 1 - terminal.Cells(figure); spare > 0 {
				part = terminal.Cut(each.Label, spare) + " " + figure
			}
			last := lines[len(lines)-1]
			if len(last) > 0 && terminal.Cells(strings.Join(append(slices.Clone(last), part), gap)) > room {
				lines = append(lines, nil)
			}
			lines[len(lines)-1] = append(lines[len(lines)-1], part)
		}
		return slices.DeleteFunc(lines, func(line []string) bool { return len(line) == 0 })
	}
	lines := fill(cells, width-2)
	if most >= 0 && len(lines) > most {
		lines = lines[:most-1]
		shown := 0
		for _, line := range lines {
			shown += len(line)
		}
		lines = append(lines, append(fill(cells[shown:], width-6)[0], "…"))
	}
	out := make([]string, len(lines))
	for i, line := range lines {
		out[i] = "  " + strings.Join(line, gap)
	}
	return out
}

package menu

import (
	"cmp"
	"math"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// LogInAgain is the act a subscription's line opens lit on, where it is offered: `spend a reset`
// spends at once, so Enter lands on it only after a move or a click there.
const LogInAgain = "log in again"

// actTexts is each act, by its word, as a line draws it with UTF-8 and without
// (menu.SUBSCRIPTION_ACTS).
var actTexts = map[string][2]string{LogInAgain: {"↻ log in again", "log in again"},
	"spend a reset": {"↻ spend a reset", "spend a reset"}, "remove": {"− remove", "- remove"}}

// Acts is what a subscription offers, its meter and its row on Subscriptions alike, by the word the
// key line names each by, where it applies (menu.subscription_acts): `log in again` while its login
// ends soon or has ended, where its harness signs that account in afresh; `spend a reset` while it
// holds one; and with remove, as its row has it, `remove`.
func (c Cell) Acts(remove bool) []string {
	var acts []string
	if c.Ends != "" && c.Harness != "" && config.SignsInAgain(c.Harness, c.Account) {
		acts = append(acts, LogInAgain)
	}
	if c.Held != "" {
		acts = append(acts, "spend a reset")
	}
	if remove {
		acts = append(acts, "remove")
	}
	return acts
}

// Subscriptions is the page `c` opens on its `Subscriptions` row, as one draw has it.
type Subscriptions struct {
	Cells       []Cell
	At          int    // the row the keys are on: a subscription's place in Cells, or len(Cells) for `+ add`
	Away        bool   // the pointer is off every row, which lights none
	On          string // the act lit on the pointed row's line, by its word; "" for none
	Top         int
	Clock, Note string
	Motion      *motion.Clock // nil, all still
}

// A SubscriptionsFrame is a draw of the page, the act it keeps lit, and where the pointer finds its
// rows and the pointed row's acts.
type SubscriptionsFrame struct {
	Lines []string
	Over  []terminal.Span
	Top   int
	On    string
	Acts  []string // the pointed subscription's, none while none is
	spots []pageSpot
}

// pageSpot is a screen row's row, -1 for none, and its acts' cells: first and last column, place.
type pageSpot struct {
	row  int
	acts [][3]int
}

// Hit is the row under the pointer and the act there, -1 for none; false off every row.
func (f SubscriptionsFrame) Hit(mouse terminal.Mouse) (row, act int, ok bool) {
	if mouse.Row <= 0 || mouse.Row > len(f.spots) || f.spots[mouse.Row-1].row < 0 {
		return 0, -1, false
	}
	spot := f.spots[mouse.Row-1]
	for _, cell := range spot.acts {
		if mouse.Column >= cell[0] && mouse.Column <= cell[1] {
			return spot.row, cell[2], true
		}
	}
	return spot.row, -1, true
}

// SubscriptionsPage is `config · subscriptions` (menu.config_subscriptions): each subscription under
// its company, named in its colour, with the main screen's meter and the resets it holds beside it,
// then `+ add a subscription`, bright only while highlighted.  The pointed row opens a line under it:
// whose login it is and its plan, or when it ends while that is soon, in amber, the resets where none
// fit beside the meter, then its acts, the one On lit and named on the key line.  On the clock the page
// comes up out of the background as it opens, its name writing itself out in its header; the pointed
// row's label and filled meter wash into its company's colour and drain as it leaves, written at their
// cells alone; and the line it opens comes up under it.
func SubscriptionsPage(s terminal.Screen, view Subscriptions) SubscriptionsFrame {
	width, lit, clock, on := s.LayoutWidth(), view.At, view.Motion, view.On
	if view.Away || lit >= len(view.Cells) {
		lit = -1
	}
	_, opening := clock.Moved("opened", lit, motion.Open) // seen with no line too, so one back is news
	var body []pageSpot
	var texts []string
	put := func(text string, spot pageSpot) {
		texts, body = append(texts, strings.TrimRight(text, " ")), append(body, spot)
	}
	type took struct {
		cell, column int
		text         string
	}
	var moving []took
	meters := meterLines(s, view.Cells, width, 1, lit, func(cell, column int, text, rest string) {
		if clock == nil {
			return // nothing moves
		}
		each, ink := view.Cells[cell], rest
		wash := motion.Drain
		if cell == lit {
			ink, wash = each.Colour, motion.Wash
		}
		now := text
		if ink != "" {
			now = s.Styled(text, ink)
		}
		if _, moved := clock.Moved("wash "+each.Provider+" "+each.Account, cell == lit, wash); moved < 1 {
			if cell != lit {
				moved = 1 - moved
			}
			now = s.Washed(text, each.Colour, rest, moved)
		}
		if cell == lit {
			now = s.Highlight(now, false)
		}
		moving = append(moving, took{cell, column, now})
	})
	var acts []string
	at := map[int]int{} // each subscription's line
	for i, each := range view.Cells {
		if i == 0 || view.Cells[i-1].Provider != each.Provider {
			put(s.Styled(each.Company, each.Colour), pageSpot{row: -1})
		}
		line := "  " + each.Label
		if len(meters) > 0 {
			line = meters[i]
		}
		beside := each.Held != "" && terminal.Cells(terminal.Plain(line)+" · "+each.Held) <= width
		if beside {
			line += s.Styled(" · "+each.Held, "dim")
		}
		at[i] = len(body)
		if i != lit {
			put(line, pageSpot{row: i})
			continue
		}
		put(s.Highlight(line, true), pageSpot{row: i})
		if acts = each.Acts(true); !slices.Contains(acts, on) {
			on = ""
		}
		held := each.Held
		if beside {
			held = ""
		}
		var told []string
		for _, part := range []string{cmp.Or(each.Ends, each.Email), each.Plan, held} {
			if part != "" {
				told = append(told, part)
			}
		}
		kind := "dim"
		if each.Ends != "" {
			kind = "amber"
		}
		for _, opened := range openedLines(s, strings.Join(told, " · "), kind, acts, on, width-4) {
			put(s.Fade(opened.text, 1-opening), pageSpot{i, opened.acts})
		}
	}
	put("", pageSpot{row: -1})
	add := "  + add a subscription"
	if !view.Away && view.At == len(view.Cells) {
		add = s.Highlight(add, true)
	}
	put(add, pageSpot{row: len(view.Cells)})

	enter := ""
	if view.At == len(view.Cells) {
		enter = "open"
	} else if slices.Contains(acts, on) {
		enter = on
	}
	keys := pageKeys(s, enter)
	var under []string
	if view.Note != "" {
		under = append(under, "")
		for _, line := range terminal.Wrap(view.Note, width-2) {
			under = append(under, "  "+s.Styled(line, "dim"))
		}
	}
	// the keys' row and the line it opens stay on the page
	room := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under))
	first, last := -1, -1
	for i, spot := range body {
		if spot.row == view.At {
			if first < 0 {
				first = i
			}
			last = i
		}
	}
	top := max(0, min(max(view.Top, last-room+1), max(0, first), max(0, len(body)-room)))
	shown := min(len(body), top+room)
	frame := SubscriptionsFrame{Top: top, On: on, Acts: acts, spots: make([]pageSpot, 2, 2+shown-top)}
	frame.spots[0].row, frame.spots[1].row = -1, -1
	frame.spots = append(frame.spots, body[top:shown]...)
	frame.Lines = Panel(s, "config · subscriptions", view.Clock, append(slices.Clone(texts[top:shown]), under...), keys)
	risen := clock.Risen()
	frame.Lines[0] = written(frame.Lines[0], "config · subscriptions", risen)
	for i := 2; i < len(frame.Lines); i++ {
		frame.Lines[i] = s.Fade(frame.Lines[i], 1-risen)
	}
	for _, each := range moving {
		if line := at[each.cell]; line >= top && line < shown {
			frame.Over = append(frame.Over, terminal.Span{Row: 3 + line - top, Column: each.column, Text: s.Fade(each.text, 1-risen)})
		}
	}
	return frame
}

// A pageLine is a line a pointed row opens, with its acts' cells: first and last column, place.
type pageLine struct {
	text string
	acts [][3]int
}

// openedLines is the line a pointed row opens: told in kind, then each act three spaces apart, the
// one on lit, wrapped in room cells and never cut; each line with its acts' cells (menu.opened_line).
func openedLines(s terminal.Screen, told, kind string, acts []string, on string, room int) []pageLine {
	type piece struct {
		text string
		act  int
	}
	var pieces []piece
	for _, part := range terminal.Wrap(told, room) {
		if part != "" {
			pieces = append(pieces, piece{s.Styled(part, kind), -1})
		}
	}
	for i, act := range acts {
		text := actText(s, act)
		if act == on {
			text = s.Lit(text)
		}
		pieces = append(pieces, piece{text, i})
	}
	lines := []pageLine{{text: "    "}}
	used := 0
	for _, each := range pieces {
		wide := terminal.Cells(each.text)
		if used > 0 && used+3+wide > room {
			lines, used = append(lines, pageLine{text: "    "}), 0
		}
		gap, line := 0, &lines[len(lines)-1]
		if used > 0 {
			gap = 3
		}
		if each.act >= 0 {
			line.acts = append(line.acts, [3]int{5 + used + gap, 4 + used + gap + wide, each.act})
		}
		line.text += strings.Repeat(" ", gap) + each.text
		used += gap + wide
	}
	return lines
}

// written is a page's header with its name written out to x of it, 0 to 1, as the page opens: the
// cells after it blank (motion.titled).
func written(header, name string, x float64) string {
	rest, whole := strings.CutPrefix(header, "agentkit · "+name)
	if !whole || x >= 1 {
		return header
	}
	all := []rune(" · " + name)
	shown := string(all[:int(math.RoundToEven(float64(len(all))*max(0, x)))])
	return "agentkit" + shown + strings.Repeat(" ", terminal.Cells(string(all))-terminal.Cells(shown)) + rest
}

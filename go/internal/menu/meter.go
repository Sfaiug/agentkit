package menu

import (
	"slices"
	"strings"

	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

// A meterSpot is where a subscription's cell sits on the ak screen's grid: its screen row, its first
// and last column, and its place in the cells (menu.meter_spots).
type meterSpot struct{ row, first, last, cell int }

// meterAt is the cell the pointer is on, -1 for none.
func (f Frame) meterAt(mouse terminal.Mouse) int {
	for _, spot := range f.meters {
		if mouse.Row == spot.row && mouse.Column >= spot.first && mouse.Column <= spot.last {
			return spot.cell
		}
	}
	return -1
}

// Meter is the cell a click on its meter opens, its place in the cells; -1 for any other key.
func (f Frame) Meter(key terminal.Key) int {
	if mouse := key.Mouse; key.Name == "pointer" && mouse.Released && mouse.Button&3 == 0 && mouse.Button&64 == 0 {
		return f.meterAt(mouse)
	}
	return -1
}

// usageDetail is what the line under the grid says of a cell while the pointer is on it
// (menu.usage_detail): its label in its company's colour, then, joined with ` · `, a login that ends
// soon in amber and `click to log in again`, and its reading's notes, as many as fit in width; the
// label gives way past the notes but before the login.
func usageDetail(s terminal.Screen, cell Cell, width int) string {
	notes := cell.Notes
	if cell.Ends != "" {
		notes = append([]usage.Note{{Rank: -2, Text: cell.Ends}, {Rank: -2, Text: "click to log in again"}}, notes...)
	}
	room, held := width-4, terminal.Cells(cell.Ends)
	if held > room {
		held = 0
	}
	label := terminal.Cut(cell.Label, room-held)
	var parts []string
	for _, note := range fitting(notes, room-terminal.Cells(label)) {
		switch {
		case note == cell.Ends:
			note = s.Styled(note, "amber")
		case strings.HasPrefix(note, "?"):
			note = s.Styled("?", "amber") + s.Styled(note[1:], "dim")
		default:
			note = s.Styled(note, "dim")
		}
		parts = append(parts, note)
	}
	return s.Styled(label, cell.Colour) + "  " + strings.Join(parts, s.Styled(" · ", "dim"))
}

// fitting is the notes that fit in room cells, offered lowest rank first and drawn in their own
// order: one too long gives way alone, never the ones after it (menu.fitting).
func fitting(notes []usage.Note, room int) []string {
	order := make([]int, len(notes))
	for i := range order {
		order[i] = i
	}
	slices.SortStableFunc(order, func(a, b int) int { return notes[a].Rank - notes[b].Rank })
	kept, used := map[int]bool{}, 0
	for _, i := range order {
		needs := terminal.Cells(notes[i].Text)
		if len(kept) > 0 {
			needs += 3
		}
		if used+needs <= room {
			kept[i], used = true, used+needs
		}
	}
	var fit []string
	for i, note := range notes {
		if kept[i] {
			fit = append(fit, note.Text)
		}
	}
	return fit
}

// ActsFrame is a meter's list (menu.meter_acts), under its label: what it offers, each by its text,
// the act the highlight is on lit while the pointer is not away from it, and the key line naming
// what Enter does there; nothing is lit while the highlight is on no act.
func ActsFrame(s terminal.Screen, label, clock string, acts []string, h Highlight) Frame {
	frame := Frame{order: acts, width: s.Width(), height: s.Height(), spots: []string{"", ""}}
	if slices.Contains(acts, h.Cursor) {
		frame.cursor = h.Cursor
	}
	var body []string
	for _, act := range acts {
		line := "  " + terminal.Cut(actText(s, act), s.Width()-3)
		if act == frame.cursor && !h.Hidden {
			line = s.Highlight(line, true)
		}
		body, frame.spots = append(body, line), append(frame.spots, act)
	}
	frame.Lines = Panel(s, label, clock, body, pageKeys(s, frame.cursor))
	return frame
}

// actText is an act as a line draws it, with UTF-8 or without (menu.act_text).
func actText(s terminal.Screen, act string) string {
	if s.ASCII() {
		return actTexts[act][1]
	}
	return actTexts[act][0]
}

// pageKeys is a page's key line: moves, then Enter named for what it does where it does something,
// then Esc back.
func pageKeys(s terminal.Screen, enter string) string {
	keys := "↑↓←→ move   "
	if enter != "" {
		keys += "⏎ " + enter + "   "
	}
	keys += "esc back"
	if s.ASCII() {
		keys = strings.NewReplacer("↑↓←→", "arrows", "⏎", "enter").Replace(keys)
	}
	return keys
}

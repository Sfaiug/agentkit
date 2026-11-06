package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// AddSteps is the lists a harness that runs any provider it can log in to opens under `+ add a
// subscription`, each under the last (menu.ADD_STEPS).
var AddSteps = []string{"model", "effort"}

// An AddList is that harness's list as one draw has it (menu.config_add).
type AddList struct {
	Title, Clock, Note string
	Picked             [][]string // each step chosen so far, by its choice's texts
	Choices            [][]string // the step being chosen's, each by its texts, in columns
	At, Top            int        // the choice lit, the line shown first
	Away               bool       // the pointer is off every choice, which lights none
	Finding            *string    // what is typed after `/`, which the choices hold; nil while not finding
	Enter              string     // what Enter does on the choice lit, "" for nothing
}

// An AddFrame is a draw of the list, the line it shows first and each screen row's choice, -1 for
// none.
type AddFrame struct {
	Lines []string
	Top   int
	spots []int
}

// Hit is the choice under the pointer; false off every choice.
func (f AddFrame) Hit(mouse terminal.Mouse) (int, bool) {
	if mouse.Row <= 0 || mouse.Row > len(f.spots) || f.spots[mouse.Row-1] < 0 {
		return 0, false
	}
	return f.spots[mouse.Row-1], true
}

// AddPage is the list drawn (menu.add_body): each step chosen so far on a line of its own, `model
// Acme 4 · Acme Cloud`, then the step being chosen, with `/` and what is found while finding,
// then its choices in columns, the one At lit; a choice's mark keeps up to half the row, and its
// label gives way before its id.  The note goes under it, and a list past the screen offers `/ find`.
func AddPage(s terminal.Screen, view AddList) AddFrame {
	room, wide := s.LayoutWidth(), 0
	for _, step := range AddSteps {
		wide = max(wide, terminal.Cells(step))
	}
	var body []string
	for i, texts := range view.Picked {
		var shown []string
		for _, text := range texts[:min(2, len(texts))] {
			if text != "" {
				shown = append(shown, text)
			}
		}
		body = append(body, "  "+terminal.Pad(AddSteps[i], wide)+"  "+terminal.Cut(strings.Join(shown, " · "), room-4-wide))
	}
	step := "  " + AddSteps[len(view.Picked)]
	if view.Finding != nil {
		step += "  /" + *view.Finding
	}
	body = append(body, step)
	columns := 0
	if len(view.Choices) > 0 {
		columns = len(view.Choices[0])
	}
	widths := make([]int, columns)
	for _, texts := range view.Choices {
		for i := range widths {
			widths[i] = max(widths[i], terminal.Cells(texts[i]))
		}
	}
	left := room - 4 - 2*max(0, columns-1)
	labels := columns
	if columns > 1 {
		labels--
		widths[labels] = min(widths[labels], left/2)
		left -= widths[labels]
	}
	for i := range labels {
		widths[i] = min(widths[i], max(0, left))
		left -= widths[i]
	}
	first := len(body)
	for at, texts := range view.Choices {
		var parts []string
		for i, room := range widths {
			text := terminal.Cut(texts[i], room)
			if i > 0 {
				text = s.Styled(text, "dim")
			}
			parts = append(parts, text+strings.Repeat(" ", max(0, room-terminal.Cells(text))))
		}
		line := strings.TrimRight("    "+strings.Join(parts, "  "), " ")
		if at == view.At && !view.Away {
			line = s.Highlight(line, true)
		}
		body = append(body, line)
	}
	var under []string
	if view.Note != "" {
		under = append(under, "")
		for _, part := range terminal.Wrap(view.Note, room-2) {
			under = append(under, s.Styled("  "+part, "dim"))
		}
	}
	keys := pageKeys(s, view.Enter)
	height := func() int { return max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under)) }
	rows := height()
	if view.Finding == nil && len(body) > rows {
		keys = strings.Replace(keys, "   esc back", "   / find   esc back", 1)
		rows = height()
	}
	drawn := len(body) - 1
	if view.At < len(view.Choices) {
		drawn = first + view.At
	}
	top := max(0, min(max(view.Top, drawn-rows+1), drawn, len(body)-rows))
	shown := body[top:min(len(body), top+rows)]
	frame := AddFrame{Top: top, spots: []int{-1, -1}}
	for line := range shown {
		frame.spots = append(frame.spots, top+line-first) // a choice's place, below 0 for none
	}
	for i, spot := range frame.spots {
		if spot < 0 || spot >= len(view.Choices) {
			frame.spots[i] = -1
		}
	}
	frame.Lines = Panel(s, view.Title, view.Clock, append(shown, under...), keys)
	return frame
}

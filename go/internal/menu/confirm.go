package menu

import (
	"slices"
	"strings"

	"agentkit/internal/terminal"
)

// Confirm puts the shared Keep/action card under name's row. Only its choices can be reached
// while it is up; the underlying frame is drawn without a highlight or an open detail.
func (f Frame) Confirm(s terminal.Screen, name, question, meaning, action string, h Highlight) Frame {
	start, at := len(f.spots), 0
	for i, each := range f.spots {
		if each == name {
			start = min(start, i)
			at = i + 1
		}
	}
	if at == 0 {
		return Frame{}
	}
	card := []row{{}}
	for i, text := range []string{question, meaning} {
		for _, line := range terminal.Wrap(text, max(1, min(f.width, 120)-2)) {
			if i == 1 {
				line = s.Styled(line, "dim")
			}
			card = append(card, row{line: "  " + line})
		}
	}
	keep, end := "✓ Keep", "✗ "+action
	if s.ASCII() {
		keep, end = "v Keep", "x "+action
	}
	card = append(card, row{"  " + keep, "Keep"}, row{"  " + s.Styled(end, "amber"), action}, row{})
	if h.Cursor != action {
		h.Cursor = "Keep"
	}
	keys := "↑↓←→ move   ⏎ "
	if s.ASCII() {
		keys = "arrows move   enter "
	}
	footer := keyLine(s, keys+strings.ToLower(h.Cursor)+"   esc back", f.width, "")
	body := make([]row, len(f.spots))
	for i := range body {
		body[i].line = f.Lines[i]
	}
	body = slices.Insert(body, at, card...)
	top := 0
	if len(body) >= 2 && strings.HasPrefix(terminal.Plain(body[0].line), "agentkit") {
		top = 2
	}
	room := max(1, f.height-len(footer)-2-top)
	skip := min(len(body)-top, max(0, at-top+len(card)-room))
	// Never leave an actionable card without the whole row identifying its target.
	if top+skip > start {
		return Frame{}
	}
	body = append(body[:top:top], body[top+skip:min(len(body), top+skip+room)]...)
	// The card's trailing blank can share the blank above the keys on a short screen.
	body = body[:min(len(body), max(0, f.height-len(footer)-3))]
	choices := []string{"Keep", action}
	shown := Frame{cursor: h.Cursor, hidden: h.Hidden, order: choices, turns: choices, page: slices.Index(choices, h.Cursor), width: f.width, height: f.height}
	for _, each := range body {
		line := each.line
		if each.seat == h.Cursor && !h.Hidden {
			line = s.Highlight(line, true)
		}
		shown.Lines = append(shown.Lines, line)
		shown.spots = append(shown.spots, each.seat)
	}
	for len(shown.Lines) < f.height-len(footer)-3 {
		shown.Lines = append(shown.Lines, "")
	}
	shown.Lines = append(shown.Lines, "")
	shown.Lines = append(shown.Lines, footer...)
	return shown
}

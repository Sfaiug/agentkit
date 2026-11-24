package terminal

import (
	"cmp"
	"strings"
)

// Selected is line with its cells first to last, counted from 1, on the theme's selection, every
// style in them kept and any past its end blank (terminal.backed): what the pointer is on.  With
// no colour line is as it is.  A reverse inside them gives way to the selection, so the pointer
// and the keys never show two.
func (s Screen) Selected(line string, first, last int) string {
	if s.depth == 0 {
		return line
	}
	back, off := s.ink(colourOf("selection", s.theme), "48"), "49"
	var out strings.Builder
	at, on, past := 0, false, false
	put := func(token string, escape bool) {
		if !on && !past && at+1 >= first {
			out.WriteString("\x1b[" + back + "m")
			on = true
		} else if on && at >= last {
			out.WriteString("\x1b[" + off + "m")
			on, past = false, true
		}
		if on && escape && strings.HasSuffix(token, "m") {
			if params := token[2 : len(token)-1]; params == "7" {
				token = "\x1b[" + back + "m"
			} else {
				token = "\x1b[" + cmp.Or(params, "0") + ";" + back + "m"
			}
		}
		out.WriteString(token)
		if !escape {
			at += Cells(token)
		}
	}
	from := 0
	for _, escape := range ansi.FindAllStringIndex(line, -1) {
		for _, r := range line[from:escape[0]] {
			put(string(r), false)
		}
		put(line[escape[0]:escape[1]], true)
		from = escape[1]
	}
	for _, r := range line[from:] {
		put(string(r), false)
	}
	if on {
		out.WriteString(strings.Repeat(" ", max(0, last-at)) + "\x1b[" + off + "m")
	}
	return out.String()
}

// Band is a highlighted row (Highlight) Enter or a click acts on as a whole, on the selection from its
// first column to width, the layout's last.
func (s Screen) Band(line string, width int) string {
	return s.Selected(line, 1, width)
}

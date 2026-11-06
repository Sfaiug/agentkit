package menu

import (
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

// PickerLines draws the draft's model marks, grouped by harness, with effort beside each mark.
func (d *Draft) PickerLines(s terminal.Screen, clock string) []string {
	label, tall, word := 1, 0, 0
	for _, name := range d.Names {
		label = max(label, terminal.Cells(config.ModelName(name, d.Models)))
		levels := d.Levels[name]
		if len(levels) > 1 {
			tall = max(tall, len(levels))
		}
		for _, level := range levels {
			word = max(word, terminal.Cells(level))
		}
		for _, key := range config.RoleEfforts {
			word = max(word, terminal.Cells(d.effort(name, key)))
		}
	}
	room := s.LayoutWidth()
	if 2+label+6+3*(4+tall+2+word) > room {
		tall = 0
	}
	effortWidth := word
	if tall > 0 {
		effortWidth += tall + 2
	}
	roleWidth := 4 + effortWidth
	folded := 3+3*(2+roleWidth) > room
	if folded {
		label = min(label, max(1, room-2))
	} else {
		label = min(label, max(1, room-2-3*(2+roleWidth)))
	}
	title := terminal.Cut("agentkit · new session", max(1, room-len(clock)-1))
	lines := []string{title + strings.Repeat(" ", max(1, room-terminal.Cells(title)-len(clock))) + clock,
		s.Styled(strings.Repeat("─", room), "dim"), ""}
	heads := []string{"orch", "builds", "reviews"}
	if !folded {
		head := strings.Repeat(" ", 2+label)
		for _, name := range heads {
			head += "  " + terminal.Pad(name, roleWidth)
		}
		lines = append(lines, s.Styled(strings.TrimRight(head, " "), "dim"))
	}
	harness, focus := "", 0
	for at, name := range d.Names {
		model := d.Models[name]
		if model.Harness != harness {
			harness = model.Harness
			lines = append(lines, s.Bold(config.HarnessName(harness)))
		}
		marks := d.marks(name)
		line := "  " + terminal.Pad(config.ModelName(name, d.Models), label)
		var own []string
		for column, marked := range marks {
			glyph := "□"
			if column == 0 {
				glyph = "○"
			}
			if marked {
				glyph = "■"
				if column == 0 {
					glyph = "●"
				}
			}
			if s.ASCII() {
				glyph = map[string]string{"□": ".", "○": ".", "■": "x", "●": "*"}[glyph]
			}
			mark := " " + glyph + " "
			if at == d.At && column == d.Column {
				mark = "[" + glyph + "]"
			}
			text := ""
			if marked {
				effort := d.effort(name, config.RoleEfforts[column])
				if tall > 0 {
					levels := d.Levels[name]
					cells := strings.Join(s.EffortCells(len(levels), slices.Index(levels, effort)+1), "")
					text = padded(cells, tall+2)
				}
				if at == d.At && column+3 == d.Column {
					effort = s.Reverse(effort)
				}
				text += effort
			}
			part := padded(mark, 4) + padded(text, effortWidth)
			if folded {
				own = append(own, "    "+terminal.Pad(heads[column], 7)+part)
			} else {
				line += "  " + part
			}
		}
		own = append([]string{line}, own...)
		for n, part := range own {
			part = strings.TrimRight(part, " ")
			if at == d.At {
				part = s.Highlight(part, n == 0)
				// The line the keys act on: folded, the cursor's role has its own line under the label.
				if !folded || n == 1+d.Column%3 {
					focus = len(lines)
				}
			}
			lines = append(lines, part)
		}
	}
	act := "mark"
	if d.Column >= 3 {
		act = "step"
	}
	keys := "↑↓←→ move   ␣ " + act + "   ⏎ start   esc back"
	if s.ASCII() {
		keys = "arrows move   space " + act + "   enter start   esc back"
	}
	keysLines := keyLine(s, keys, s.Width(), "")
	// Keep the line the keys act on in view on a short terminal, retaining the frame and keys.
	if most := max(1, s.Height()-5-len(keysLines)); len(lines)-3 > most {
		start := min(max(0, focus-3-most+1), len(lines)-3-most)
		lines = append(lines[:3:3], lines[3+start:3+start+most]...)
	}
	return append(append(lines, ""), keysLines...)
}

func (d *Draft) effort(name, key string) string {
	model := d.Models[name]
	if effort, set := model.Efforts[key]; set {
		return effort
	}
	return model.Efforts["effort"]
}

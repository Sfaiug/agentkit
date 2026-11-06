package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// A ModelRow is a harness's row on Models, or one its row opens: a model, or with Login a provider
// to log in to.
type ModelRow struct {
	Name, Value, Colour   string
	Choice, Marked, Login bool
}

// ConfigModelsFrame uses c's frame and hit map for the harness rows and their open model list.
func ConfigModelsFrame(s terminal.Screen, rows []ModelRow, at, top int, clock, version, note string) MatrixFrame {
	keys := "↑↓←→ move   ⏎ open   esc back"
	if rows[at].Login {
		keys = "↑↓←→ move   ⏎ log in   esc back"
	} else if rows[at].Choice {
		keys = "↑↓←→ move   ␣ mark   ⏎ close   esc back"
	}
	if s.ASCII() {
		keys = strings.NewReplacer("↑↓←→", "arrows", "␣", "space", "⏎", "enter").Replace(keys)
	}
	width, room := 0, s.LayoutWidth()
	for _, row := range rows {
		if !row.Choice {
			width = max(width, terminal.Cells(row.Name))
		}
	}
	width = min(width, max(1, room-4))
	body := []matrixRow{}
	first, last := 0, 0
	for i, row := range rows {
		if i == at {
			first = len(body)
		}
		folded := false
		lead, text := "    ", row.Name
		if row.Login {
			text += " log in"
		} else if row.Choice {
			mark := "□"
			if row.Marked {
				mark = "■"
			}
			if s.ASCII() {
				mark = "-"
				if row.Marked {
					mark = "#"
				}
			}
			text = mark + " " + text
		} else {
			lead = "  " + terminal.Pad(s.Styled(terminal.Cut(row.Name, width), row.Colour), width) + "  "
			text = row.Value
			for _, word := range strings.Fields(text) {
				folded = folded || terminal.Cells(word) > room-terminal.Cells(lead)
			}
			if folded {
				line := "  " + s.Styled(terminal.Cut(row.Name, room-2), row.Colour)
				if i == at {
					line = s.Highlight(line, true)
				}
				body = append(body, matrixRow{line: line, row: i, cells: []matrixCell{{1, room, 0}}})
				lead = "    "
			}
		}
		parts := terminal.Wrap(text, max(1, room-terminal.Cells(lead)))
		if len(parts) == 0 {
			parts = []string{""}
		}
		for n, part := range parts {
			line := strings.TrimRight(lead+part, " ")
			if i == at {
				line = s.Highlight(line, n == 0 && !folded)
			}
			body = append(body, matrixRow{line: line, row: i, cells: []matrixCell{{1, room, 0}}})
			lead = strings.Repeat(" ", terminal.Cells(lead))
		}
		if i == at {
			last = len(body) - 1
		}
	}
	under := []string{"", "  " + s.Styled("Version "+version, "dim")}
	for _, line := range terminal.Wrap(strings.TrimSpace(note+"\nSpace on a model under its harness takes it in or out of the config."), room-2) {
		under = append(under, "  "+s.Styled(line, "dim"))
	}
	height := max(1, s.Height()-4-len(under)-len(keyLine(s, keys, s.Width(), "")))
	top = max(0, min(max(top, last-height+1), first, max(0, len(body)-height)))
	lines := []string{}
	spots := []matrixRow{{row: -1}, {row: -1}}
	for _, row := range body[top:min(top+height, len(body))] {
		lines = append(lines, row.line)
		spots = append(spots, row)
	}
	return MatrixFrame{Panel(s, "config · models", clock, append(lines, under...), keys), top, spots}
}

package menu

import (
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/features"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// headingRow is a project's heading (menu.v5o_header): its checkout's name in bold, the seats
// filed under none a dim one.  One naming its feature switches (switches, by checkout: how many
// are hidden) is a row the highlight rests on, its checkout its name, with how many are hidden from
// everyone dim at its right where the whole count fits beside the highlight's mark and the name.
func headingRow(s terminal.Screen, each project, width int, switches map[string]int) row {
	room := max(1, min(width, 120)) - 2
	if !each.filed {
		return row{line: s.Styled(terminal.Cut(unfiled, room), "dim")}
	}
	hidden, named := switches[each.name]
	count, spare, at := "", room, ""
	if hidden > 0 {
		count = strconv.Itoa(hidden) + " hidden feature"
		if hidden > 1 {
			count += "s"
		}
	}
	if terminal.Cells(count) > room-3 {
		count = ""
	} else if count != "" {
		spare -= terminal.Cells(count) + 2
	}
	name := terminal.Cut(base(each.name), spare)
	line := s.Bold(name)
	if count != "" {
		line += strings.Repeat(" ", room-terminal.Cells(name)-terminal.Cells(count)) + s.Styled(count, "dim")
	}
	if named {
		at = each.name
	}
	return row{line, at}
}

// A FeaturesView is what a project's switches screen is drawn from: the project's name, its
// reading, the feature the keys are on (the first where it is none of them) and the mark under it,
// 0 `you` and 1 `everyone`, the first line of the rows the page shows, and the clock the rule
// glides on while a list is awaited, nil for a still one.
type FeaturesView struct {
	Title, Clock string
	features.Reading
	At          string
	Column, Top int
	Waiting     *motion.Clock
}

// Here is which of the rows the keys are on: At, else the first; -1 for none.
func (view FeaturesView) Here() int {
	if len(view.Rows) == 0 {
		return -1
	}
	return max(0, slices.IndexFunc(view.Rows, func(each features.Switch) bool { return each.ID == view.At }))
}

// FeaturesFrame is `agentkit · <project>`: its switches, one row a feature, with a mark under
// `you` and under `everyone` (menu.features_body), paged so the feature the keys are on is shown,
// and under them why there are none, or why the last list failed.
func FeaturesFrame(s terminal.Screen, view FeaturesView) MatrixFrame {
	keys, on, off, fixed := "↑↓←→ move   ␣ mark   esc back", "●", "○", "—"
	if s.ASCII() {
		keys, on, off, fixed = "arrows move   space mark   esc back", "*", ".", "-"
	}
	heads := []string{"you", "everyone"}
	var body []matrixRow
	here := view.Here()
	if here >= 0 {
		label, width := 0, 2
		for _, head := range heads {
			width += 2 + terminal.Cells(head)
		}
		for _, each := range view.Rows {
			label = max(label, terminal.Cells(each.Name))
		}
		label = min(label, max(1, s.LayoutWidth()-width))
		head := strings.Repeat(" ", 2+label)
		for _, each := range heads {
			head += "  " + each
		}
		body = append(body, matrixRow{line: s.Styled(head, "dim"), row: -1})
		for i, each := range view.Rows {
			marks := []string{off, off}
			if each.Everyone {
				marks = []string{on, on}
			} else if each.You {
				marks[0] = on
			}
			if each.Fixed {
				marks[0] = fixed
			}
			shown := terminal.Cut(each.Name, label)
			line, first, cells := "  "+shown+strings.Repeat(" ", label-terminal.Cells(shown)), 2+label+1, []matrixCell(nil)
			for column, mark := range marks {
				kind := []string{"accent", "done"}[column]
				if mark != on {
					kind = "dim"
				}
				size := terminal.Cells(heads[column])
				line += "  " + s.Toggle(mark, size, i == here && column == view.Column, kind)
				cells = append(cells, matrixCell{first + 2, first + 1 + size, column})
				first += 2 + size
			}
			line = strings.TrimRight(line, " ")
			if i == here {
				line = s.Highlight(line, true)
			}
			body = append(body, matrixRow{line, i, cells})
		}
	}
	why := view.Why
	if why == "" && view.Rows == nil {
		why = "asking for its features"
	} else if why == "" && len(view.Rows) == 0 {
		why = "no features"
	}
	var said []string
	if why != "" {
		said = []string{"", s.Styled("  "+terminal.Cut(why, s.LayoutWidth()-2), "dim")}
	}
	// the page that holds the highlighted feature, moved the least from where it stood
	room := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(said))
	line := max(0, here+1)
	top := max(0, min(max(view.Top, line-room+1), line, len(body)-room))
	shown := body[top:min(top+room, len(body))]
	lines, spots := []string{}, []matrixRow{{row: -1}, {row: -1}}
	for _, each := range shown {
		lines = append(lines, each.line)
	}
	lines = Panel(s, view.Title, view.Clock, append(lines, said...), keys)
	if view.Waiting != nil {
		lines[1] = view.Waiting.WaitingRule(s, s.LayoutWidth())
	}
	return MatrixFrame{lines, top, append(spots, shown...)}
}

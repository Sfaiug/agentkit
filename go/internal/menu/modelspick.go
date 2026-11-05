package menu

import (
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

type CompareLine struct{ Text, Release, Maker string }

// CompareLines keeps the lineup's maker and strength order, one row per release.
func CompareLines(s terminal.Screen, lineup []quality.Row, marks map[string]bool, find string) []CompareLine {
	plain := func(text string) string {
		return strings.Map(func(r rune) rune {
			if unicode.IsLetter(r) || unicode.IsNumber(r) {
				return unicode.ToLower(r)
			}
			return -1
		}, text)
	}
	on, off := "■", "□"
	if s.ASCII() {
		on, off = "x", "."
	}
	marked := func(onIt bool) string {
		if onIt {
			return on
		}
		return off
	}
	makers, seen := []string{}, map[string]bool{}
	under := map[string][]quality.Row{}
	for _, row := range lineup {
		if seen[row.Release] {
			continue
		}
		seen[row.Release] = true
		if _, held := under[row.Maker]; !held {
			makers = append(makers, row.Maker)
		}
		under[row.Maker] = append(under[row.Maker], row)
	}
	lines := []CompareLine{{Text: fmt.Sprintf("  %s all %d models", marked(len(marks) == 0), len(seen))}}
	for _, maker := range makers {
		headed := false
		for _, row := range under[maker] {
			if !strings.Contains(plain(row.Name), plain(find)) {
				continue
			}
			if !headed {
				lines = append(lines, CompareLine{Text: "  " + terminal.Cut(maker, s.LayoutWidth()-2), Maker: maker})
				headed = true
			}
			lines = append(lines, CompareLine{Text: "    " + marked(marks[row.Release]) + " " + terminal.Cut(row.Name, s.LayoutWidth()-6), Release: row.Release, Maker: maker})
		}
	}
	return lines
}

// CompareFrame scrolls the list with the highlight, counting makers entirely out of view.
func CompareFrame(s terminal.Screen, title string, rows []CompareLine, marks map[string]bool, total int, find string, at, top int, note string) MatrixFrame {
	keys, caret := "↑↓ move   ␣ mark   type to find   esc done", "▏"
	if s.ASCII() {
		keys, caret = "up/down move   space mark   type to find   esc done", "_"
	}
	head, count := "  models to compare", fmt.Sprintf("all %d compared", total)
	if len(marks) > 0 {
		count = fmt.Sprintf("%d of %d marked", len(marks), total)
	}
	heads := []string{head, "  " + count}
	if gap := s.LayoutWidth() - terminal.Cells(head+count); gap >= terminal.Cells(count) {
		heads = []string{head + strings.Repeat(" ", gap) + count}
	}
	heads = append(heads, "  find  "+s.Bold(terminal.Cut(find, s.LayoutWidth()-9))+s.Styled(caret, "accent"))
	var notes []string
	for _, part := range terminal.Wrap(note, s.LayoutWidth()-2) {
		notes = append(notes, "  "+s.Styled(part, "dim"))
	}
	tall := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(heads)-len(notes))
	if len(rows) <= tall {
		tall = len(rows)
	} else {
		tall = max(1, tall-2)
	}
	top = max(0, min(max(top, at-tall+1), at, len(rows)-tall))
	shown := rows[top : top+tall]
	cut := func(rows []CompareLine, where string) string {
		makers := map[string]bool{}
		for _, row := range rows {
			makers[row.Maker] = true
		}
		for _, row := range shown {
			delete(makers, row.Maker)
		}
		delete(makers, "")
		if len(makers) == 0 {
			return ""
		}
		plural := ""
		if len(makers) > 1 {
			plural = "s"
		}
		return fmt.Sprintf("  %d more maker%s %s", len(makers), plural, where)
	}
	lines := heads
	spots := slices.Repeat([]matrixRow{{row: -1}}, 2+len(heads))
	if above := cut(rows[:top], "above"); above != "" {
		lines = append(lines, s.Styled(above, "dim"))
		spots = append(spots, matrixRow{row: -1})
	}
	for i, row := range shown {
		line, spot := row.Text, top+i
		if spot == at {
			line = s.Highlight(line, true)
		}
		if spot != 0 && row.Release == "" {
			spot = -1
		}
		lines = append(lines, line)
		first := len(line) - len(strings.TrimLeft(line, " ")) + 1
		spots = append(spots, matrixRow{row: spot, cells: []matrixCell{{first, terminal.Cells(line), 0}}})
	}
	if below := cut(rows[top+tall:], "below"); below != "" {
		lines = append(lines, s.Styled(below, "dim"))
	}
	lines = append(lines, notes...)
	return MatrixFrame{Panel(s, title, time.Now().Format("15:04"), lines, keys), top, spots}
}

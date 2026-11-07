package menu

import "agentkit/internal/terminal"

// fieldLine is the line of the field open under a page's row (terminal.field's): what was typed,
// its end where it is wider than the room, else the placeholder, dim, until a key replaces it.
func fieldLine(s terminal.Screen, typed, placeholder string) string {
	const prompt = "    "
	room := max(1, s.LayoutWidth()-terminal.Cells(prompt)-1)
	if typed == "" {
		return prompt + s.Styled(terminal.Cut(placeholder, room), "dim")
	}
	runes, used := []rune(typed), 0
	end := len(runes)
	for end > 0 && used+terminal.Cells(string(runes[end-1])) <= room {
		end--
		used += terminal.Cells(string(runes[end]))
	}
	return prompt + string(runes[end:])
}

package menu

import "agentkit/internal/terminal"

// piped is what each row drawn for a pipe opens under it, as nothing is highlighted there to open
// it (menu.opened): the detail of a seat not working that says something, and of one holding words
// typed and not sent.
func piped(s terminal.Screen, seats []Seat, room int) map[string][]string {
	opened := map[string][]string{}
	for _, seat := range seats {
		if seat.Word != "working" && seat.Said != "" || seat.Unsent != "" {
			opened[seat.Name] = detail(s, seat, room, nil)
		}
	}
	return opened
}

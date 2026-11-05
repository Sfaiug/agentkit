package menu

import (
	"fmt"
	"strings"
	"testing"
)

func TestAnUnboundedMenuListsEverySeatWithoutScreenPadding(t *testing.T) {
	view := fourSeats()
	view.Seats = nil
	for i := 1; i <= 40; i++ {
		view.Seats = append(view.Seats, Seat{Number: i, Name: fmt.Sprintf("seat-%02d", i), Model: "Opus 5.5", Word: "idle"})
	}
	for _, width := range []int{100, 40, 24} {
		lines := Lines(view, width, 0)
		text := strings.Join(lines, "\n")
		if !strings.HasPrefix(text, "agentkit") || !strings.HasSuffix(text, "esc leave") {
			t.Fatalf("%d columns: incomplete frame", width)
		}
		for _, seat := range view.Seats {
			if !strings.Contains(text, seat.Name) {
				t.Errorf("%d columns: missing %s", width, seat.Name)
			}
		}
		keys := len(lines)
		for keys > 0 && lines[keys-1] != "" {
			keys--
		}
		if keys < 2 || lines[keys-2] == "" {
			t.Errorf("%d columns: padding before the key line", width)
		}
	}
}

//go:build linux || darwin

package cli

import (
	"io"
	"strings"
	"testing"

	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// A mouse release whose press began on the previous screen neither hides nor moves the highlight on
// the add page, so the next Enter picks the row the keys are on; a press and release on `esc back`
// goes back.
func TestCompanyAddIgnoresReleaseFromPreviousScreen(t *testing.T) {
	t.Setenv("COLUMNS", "80")
	t.Setenv("LINES", "24")
	others := []matrix.Company{
		{Maker: "Dyne", Models: [][2]string{{"dyne-ultra-4", "Dyne Ultra 4"}}},
		{Maker: "Bolt", Models: [][2]string{{"bolt-3", "Bolt 3"}}},
	}
	keyboard := terminal.NewKeyboard()
	frame := menu.CompanyAddFrame(keyboard.Screen(), "models · add a company", others, 0, 0, false, terminal.Mouse{})
	footerRow := len(frame.Lines)
	escCol := strings.Index(terminal.Plain(frame.Lines[footerRow-1]), "esc back") + 1
	button := func(column, row int, released bool) terminal.Key {
		return terminal.Key{Name: "pointer", Mouse: terminal.Mouse{Column: column, Row: row, Released: released}}
	}

	// Stray release over the footer does not clear the highlight: Enter picks Dyne (row 0).
	keyboard.Unread(button(escCol, footerRow, true), terminal.Key{Name: "enter"}, terminal.Key{Name: "eof"})
	if got := menuCompanyAdd("models · add a company", others, keyboard, terminal.NewPainter(io.Discard)); got != 0 {
		t.Fatalf("stray release over footer + Enter = %d, want 0", got)
	}

	// Stray release over Bolt (row 1) does not move the highlight off Dyne (row 0).
	boltRow := 0
	for i, line := range frame.Lines {
		if strings.Contains(terminal.Plain(line), "Bolt") {
			boltRow = i + 1
		}
	}
	keyboard = terminal.NewKeyboard()
	keyboard.Unread(button(4, boltRow, true), terminal.Key{Name: "enter"}, terminal.Key{Name: "eof"})
	if got := menuCompanyAdd("models · add a company", others, keyboard, terminal.NewPainter(io.Discard)); got != 0 {
		t.Fatalf("stray release over Bolt + Enter = %d, want 0", got)
	}

	// A click begun on this page over `esc back` still goes back.
	keyboard = terminal.NewKeyboard()
	keyboard.Unread(button(escCol, footerRow, false), button(escCol, footerRow, true), terminal.Key{Name: "enter"})
	if got := menuCompanyAdd("models · add a company", others, keyboard, terminal.NewPainter(io.Discard)); got != -1 {
		t.Fatalf("click on esc back = %d, want -1", got)
	}
}

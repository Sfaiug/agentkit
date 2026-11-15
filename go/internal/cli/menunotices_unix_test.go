//go:build linux || darwin

package cli

import (
	"io"
	"testing"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// A click on the note's `esc back` goes on to the menu as Esc does; a button let go there that went
// down before the note, or a click on the blank past `esc back`, leaves the note up.
func TestAClickOnEscBackLeavesTheNotice(t *testing.T) {
	t.Setenv("COLUMNS", "80")
	t.Setenv("LINES", "24")
	keyboard := terminal.NewKeyboard()
	row := len(menu.Panel(keyboard.Screen(), "note", "00:00", []string{"  update: done"}, "esc back"))
	press := func(column int, released bool) terminal.Key {
		return terminal.Key{Name: "pointer", Mouse: terminal.Mouse{Column: column, Row: row, Released: released}}
	}
	keyboard.Unread(press(3, true), press(20, false), press(20, true), press(3, false), press(3, true),
		terminal.Key{Name: "enter"}, terminal.Key{Name: "eof"})
	if !showMenuNotices([]string{"update: done"}, keyboard, terminal.NewPainter(io.Discard)) {
		t.Fatal("the note took the keyboard as gone")
	}
	if got := keyboard.ReadKey().Name; got != "enter" {
		t.Fatalf("the click on esc back left the note up: next key %q, want the Enter after it", got)
	}
}

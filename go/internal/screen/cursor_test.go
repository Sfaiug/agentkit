package screen

import "testing"

func TestTheComposersBoxIsTheBottomRunOfRowsItsPatternReads(t *testing.T) {
	rules, err := Compile(map[string]any{"composer": "[┃╹].*"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	// a quoted composer up the transcript is no box; the leading blank row keeps its place
	shown := "\n┃ an old draft\nsaid\n┃\n┃  Build · vela\n╹\nctrl+p commands"
	for row, inside := range []bool{false, false, false, true, true, true, false, false} {
		if rules.InComposer(shown, row) != inside {
			t.Errorf("row %d: inside=%v", row, !inside)
		}
	}
	if rules.InComposer("a dialog\nover it all", 0) {
		t.Error("a screen with no composer has a box")
	}
}

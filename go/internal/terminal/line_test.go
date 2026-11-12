package terminal

import "testing"

func TestShareLineDrawsItsShareInEachDepth(t *testing.T) {
	plain := Screen{}
	for _, each := range []struct {
		share float64
		size  int
		want  string
	}{
		{1, 4, "━━━━"}, {0, 4, "────"}, {0.1, 36, "━━━╸" + "────────────────────────────────"}, {0.5, 3, "━╸─"},
	} {
		if got := plain.ShareLine(each.share, each.size, "#a6adc8"); got != each.want {
			t.Errorf("%v of %d: %q", each.share, each.size, got)
		}
	}
	if got := (Screen{ascii: true}).ShareLine(0.5, 4, "#a6adc8"); got != "==--" {
		t.Errorf("ascii: %q", got)
	}
	// each cell in the colour, as Python's styled writes it
	if got, want := (Screen{depth: 24}).ShareLine(1, 2, "#a6adc8"), "\x1b[38;2;166;173;200m━\x1b[0m\x1b[38;2;166;173;200m━\x1b[0m"; got != want {
		t.Errorf("24-bit: %q, want %q", got, want)
	}
	if got, want := (Screen{depth: 8}).ShareLine(1, 2, "#a6adc8"), "\x1b[37m━━\x1b[0m"; got != want {
		t.Errorf("8 colours: %q, want %q", got, want)
	}
}

func TestEffortCellsAreALevelOfMany(t *testing.T) {
	if got := (Screen{}).EffortCells(1, 1); got != nil {
		t.Errorf("one effort is no level: %q", got)
	}
	got := (Screen{ascii: true}).EffortCells(3, 2)
	if len(got) != 3 || got[0] != "#" || got[1] != "#" || got[2] != "-" {
		t.Errorf("%q", got)
	}
}

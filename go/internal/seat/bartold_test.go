package seat

import "testing"

// Each want is statusbar._digest of the same told, so a bar Python told is left alone where Go
// would tell it the same.
func TestABarsDigestIsStatusbarsOwn(t *testing.T) {
	if got := barDigest(barTuple("! 1 other seat needs you", "it's", "é\n\"")); got != "2b0c79b01c228b45" {
		t.Errorf("right end: %s", got)
	}
	own := [][3]string{{"=a#b%:", "status", "2"}, {"=a#b%:", "set-titles-string", "a##b%% · idle"}}
	lists := barOwn(own, []barRow{{name: "a#b%", told: "dd832cf905f40942"}, {name: "c"}})
	if len(lists) != 0 {
		t.Errorf("a bar showing what it would be told is told again, or another bar is: %q", lists)
	}
	if lists := barOwn(own, []barRow{{name: "a#b%"}}); len(lists) != 1 || lists[0][len(lists[0])-1] != "dd832cf905f40942" {
		t.Errorf("a bar never told is not told whole: %q", lists)
	}
}

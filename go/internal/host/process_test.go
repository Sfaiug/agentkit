package host

import "testing"

func TestAProcessInsideItsExitHasExited(t *testing.T) {
	for _, each := range []struct {
		stat Stat
		want bool
	}{
		{Stat{State: "S"}, false},
		{Stat{State: "R", Flags: 0x400000}, false},
		{Stat{State: "Z"}, true},
		{Stat{State: "X"}, true},
		{Stat{State: "R", Flags: 0x4}, true}, // PF_EXITING: its files closed, not yet a zombie
	} {
		if got := each.stat.Exited(); got != each.want {
			t.Errorf("%+v: got %v", each.stat, got)
		}
	}
}

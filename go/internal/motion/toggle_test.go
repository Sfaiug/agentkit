package motion

import (
	"testing"
	"time"
)

func TestAMarkFillsAndEmptiesThroughItsFullShapeDimAsItsOpenOne(t *testing.T) {
	opened, clock := time.Unix(100, 0), &Clock{}
	for _, each := range []struct {
		after                  time.Duration
		key, mark, kind        string
		wantShown, wantDrawnIn string
	}{
		{0, "set", "□", "dim", "□", "dim"},
		{time.Second, "set", "■", "accent", "■", "dim"},
		{time.Second + Toggle, "set", "■", "accent", "■", "accent"},
		{time.Second + Toggle, "cleared", "●", "accent", "●", "accent"},
		{2 * time.Second, "cleared", "○", "dim", "●", "dim"},
		{2*time.Second + Toggle, "cleared", "○", "dim", "○", "dim"},
	} {
		clock.Draw(opened.Add(each.after))
		if shown, in := clock.Mark(each.key, each.mark, each.kind); shown != each.wantShown || in != each.wantDrawnIn {
			t.Errorf("%s at %v: %s in %s, want %s in %s", each.key, each.after, shown, in, each.wantShown, each.wantDrawnIn)
		}
	}
}

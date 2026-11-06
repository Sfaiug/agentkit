package seat

import (
	"testing"
	"time"

	"agentkit/internal/run"
)

// menu.back_at: the time today, the day and time within the week, the date past it.
func TestASeatOutOfUsageSaysWhenItComesBackInTheReadersOwnTime(t *testing.T) {
	now := time.Date(2026, time.October, 30, 12, 0, 0, 0, time.Local) // a Friday
	at := func(days, hour, minute int) any {
		return run.Float(float64(time.Date(2026, time.October, 30+days, hour, minute, 30, 0, time.Local).Unix()))
	}
	for _, each := range []struct {
		when any
		want string
	}{
		{at(0, 19, 20), "19:20"}, {at(1, 1, 22), "Sat 01:22"}, {at(8, 9, 0), "7 Nov"}, {nil, ""}, {"soon", ""},
	} {
		if said := backAt(each.when, now); said != each.want {
			t.Errorf("%v: %q, not %q", each.when, said, each.want)
		}
	}
}

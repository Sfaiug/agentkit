package usage

import (
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// watch.seat_account's wait: the latest of the spent windows gating the model and its provider's
// mark, the one just made standing for it; else the wait's own end, and an hour where that is past.
func TestAWaitEndsWhenTheLastSpentWindowComesBack(t *testing.T) {
	models := map[string]config.Model{"flash": {Provider: "acme"}}
	spent := &Readings{models: models, now: 100, providers: fields("acme", fields("exhausted_until", 250.0, "meters", []any{
		fields("name", "day", "used", 100, "resets_at", 200), fields("name", "week", "used", 100, "resets_at", 300),
		fields("name", "hour", "used", 40, "resets_at", 900), fields("name", "past", "used", 100, "resets_at", 50)}))}
	room := &Readings{models: models, now: 100, providers: fields("acme", fields("meters", []any{}))}
	for _, each := range []struct {
		readings          *Readings
		marked, otherwise any
		want              float64
	}{
		{spent, nil, nil, 300}, {spent, run.Float(400), nil, 400}, {spent, nil, run.Float(999), 300},
		{room, nil, run.Float(150), 150}, {room, nil, run.Float(50), 100 + dryFor}, {room, nil, nil, 100 + dryFor},
	} {
		if back, _ := run.Num(each.readings.Back("flash", each.marked, each.otherwise)); back != each.want {
			t.Errorf("%v, %v: %v, not %v", each.marked, each.otherwise, back, each.want)
		}
	}
}

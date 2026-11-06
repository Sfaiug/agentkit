package usage

import (
	"slices"
	"testing"

	"agentkit/internal/config"
)

// menu.usage_detail's notes, in the line's order: a model's own cap that differs, the 5-hour window,
// the resets in hand and why the last probe failed, the endpoint's refusal saying nothing, and why a
// reading with no week has none.
func TestTheLineUnderTheGridSaysWhatTheCellHasNoRoomFor(t *testing.T) {
	models := map[string]config.Model{"fable": {Provider: "acme", Meter: "weekly_scoped"}, "spark": {Provider: "acme"}}
	weeks := func(session int) []any {
		return []any{fields("name", "weekly_all", "used", 40, "window_secs", 604800),
			fields("name", "weekly_scoped", "used", 70, "window_secs", 604800),
			fields("name", "five", "used", session, "window_secs", sessionSecs)}
	}
	for _, each := range []struct {
		prov *Readings
		want []Note
	}{
		{&Readings{models: models, now: 100, providers: fields("acme", fields("meters", weeks(35), "resets", 2,
			"error", "unknown:  probe\ttimed out"))},
			[]Note{{1, "2 resets in hand"}, {3, "Fable 30%"}, {2, "5h 65% left"}, {1, "? probe timed out"}}},
		{&Readings{models: models, now: 100, providers: fields("acme", fields("meters", weeks(100),
			"error", "unknown: probe timed out", "probe_error", "x"))},
			[]Note{{3, "Fable 30%"}, {-1, "5h spent"}}},
		{&Readings{models: models, now: 100, providers: fields("acme", fields("meters", []any{}, "logged_in", false))},
			[]Note{{0, "no login"}}},
	} {
		if got := each.prov.Detail("acme", ""); !slices.Equal(got, each.want) {
			t.Errorf("%v, not %v", got, each.want)
		}
	}
}

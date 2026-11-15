package usage

import (
	"slices"
	"testing"

	"agentkit/internal/config"
)

// usage._gating_meters: a cap whose `scope` names a word of neither the model's id nor the name it
// is shown by is another model's and never gates it; one scoped to it does, though another model's
// `meter` claims that cap's name.
func TestACapScopedToAnotherModelNeverGatesIt(t *testing.T) {
	models := map[string]config.Model{"fable": {Provider: "acme", ID: "acme-fable-5-2"},
		"spark": {Provider: "acme", ID: "acme-spark-1", Meter: "weekly_scoped"}}
	r := &Readings{models: models, providers: fields("acme", fields("meters", []any{fields("name", "weekly_all"),
		fields("name", "weekly_scoped", "scope", "Fable"), fields("name", "spark_cap", "scope", "Spark Max")}))}
	for name, want := range map[string][]string{"fable": {"weekly_all", "weekly_scoped"}, "spark": {"weekly_all"}} {
		meters, _ := r.gating(name)
		var got []string
		for _, meter := range meters {
			got = append(got, meter.Str("name"))
		}
		if !slices.Equal(got, want) {
			t.Errorf("%s is gated by %v, want %v", name, got, want)
		}
	}
}

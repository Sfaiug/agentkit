package matrix

import (
	"reflect"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/quality"
)

func TestTakesMatchesBothListedNamesInConfiguredOrder(t *testing.T) {
	c := Configuration{Names: []string{"other", "first", "second"}, Models: map[string]config.Model{
		"other":  {Harness: "claude", ID: "acme"},
		"first":  {Harness: "codex", ID: "acme"},
		"second": {Harness: "codex", ID: "acme"},
	}}
	take := &quality.Rating{Row: quality.Row{Effort: "high", Runners: [][2]string{{"codex", "acme"}}}}
	answer := map[string]*quality.Said{
		"orchestrate": {}, "execute": {Take: take},
		"review": {Take: &quality.Rating{Row: quality.Row{Runners: [][2]string{{"codex", "unconfigured"}}}}},
	}
	want := []config.EffortStep{{Model: "first", Key: "exec_effort", Effort: "high"}}
	if got := c.Takes(answer); !reflect.DeepEqual(got, want) {
		t.Fatalf("took %v, want %v", got, want)
	}
}

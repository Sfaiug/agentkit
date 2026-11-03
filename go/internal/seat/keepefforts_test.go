package seat

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

// Before config.toml is saved each seat's record holds the efforts its models run at, as Python's
// keep_efforts writes it: a gone worker falls back to the first model offered, a record holding
// them already or not reading as a seat's is left, and so is a rename's pointer.
func TestKeepEffortsHoldsEachSeatsEffortsAsPythonDoes(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), `[models.one]
harness='claude'
model='claude-one'
effort='high'
provider='test'
[models.two]
harness='claude'
model='claude-two'
effort='medium'
exec_effort='low'
provider='test'
[models.broken]
harness='claude'
effort='high'
provider='test'
[providers.test]
mode='subscription'
`)
	state := filepath.Join(home, ".agentkit", "state")
	records := map[string][2]string{ // as written, as kept
		"alpha": {`{"orchestrator": "one", "workers": ["two"], "cwd": "/w"}`,
			`{"orchestrator": "one", "workers": ["two"], "cwd": "/w", "efforts": {"one": {"effort": "high"}, "two": {"effort": "medium", "exec_effort": "low"}}}`},
		"gone": {`{"orchestrator": "one", "workers": ["old"], "reviewers": ["two"]}`,
			`{"orchestrator": "one", "workers": ["old"], "reviewers": ["two"], "efforts": {"one": {"effort": "high"}, "two": {"effort": "medium", "exec_effort": "low"}}}`},
		"held":  {`{"orchestrator": "one", "workers": ["one"], "efforts": {"one": {"effort": "low"}}}`, ""},
		"odd":   {`{"orchestrator": "one", "workers": ["two"], "efforts": {"one": {}}}`, ""},
		"bad":   {`{"orchestrator": "one", "workers": ["broken"]}`, ""},
		"twice": {`{"orchestrator": "one", "workers": ["two", "two"]}`, ""},
		"moved": {`{"renamed": "alpha"}`, ""},
		"audit": {`{"orchestrator": "one", "workers": ["two"]}`, ""},
	}
	for name, record := range records {
		write(t, filepath.Join(state, "session-"+name+".json"), record[0])
	}
	models, _ := config.Models()
	bound, _ := config.Bind()
	offered, _ := config.Offered()
	if err := keepEfforts(state, bound.Models, models, offered); err != nil {
		t.Fatal(err)
	}
	for name, record := range records {
		want := record[1]
		if want == "" {
			want = record[0]
		}
		data, _ := os.ReadFile(filepath.Join(state, "session-"+name+".json"))
		var got, meant any
		json.Unmarshal(data, &got)
		json.Unmarshal([]byte(want), &meant)
		if encoded(t, got) != encoded(t, meant) {
			t.Errorf("%s holds %s, want %s", name, data, want)
		}
	}
}

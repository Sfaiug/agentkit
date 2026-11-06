package seat

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A seat holds what its harness's last Stop listed, else what its screen last showed running.
func TestASeatHoldsItsStopsListElseWhatItsScreenShowed(t *testing.T) {
	home := sandbox(t)
	if work := holding("acme"); len(work) != 0 {
		t.Fatal(work)
	}
	write(t, stateFile(home, "seat-acme.json"), `{"holds": ["shell"]}`)
	if work := holding("acme"); !slices.Equal(work, []string{"shell"}) {
		t.Fatal(work)
	}
	write(t, stateFile(home, "hook-acme.json"), `{"session": "acme", "event": "Stop", "at": 1, "holds": ["monitor", "subagent"]}`)
	if work := holding("acme"); !slices.Equal(work, []string{"monitor", "subagent"}) {
		t.Fatal(work)
	}
}

// What a screen showed running ended with the process a move to another account ended: the
// process started in its place holds none of it.
func TestAMoveLeavesTheEndedProcesssScreenHoldsBehind(t *testing.T) {
	home := accountHome(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"),
		strings.ReplaceAll(testConfig, "harness='claude'", "harness='antigravity'")+"accounts=['default','second']\n")
	accountMeters(t, home, 100, 10)
	rule := strings.Repeat("─", 40)
	drawn(t, home, "acme", rule+"\n>\n"+rule+"\n● [12:08:46] sleep 45 running\n"+rule+
		"\n? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents · 1 task(s) · /tasks\n")
	accountAdapter(t, home, "case \"$1\" in auth) exit 0 ;; interactive) echo 'sleep 600' ;; esac\n")
	if err := os.Rename(filepath.Join(home, "adapters", "claude.sh"), filepath.Join(home, "adapters", "antigravity.sh")); err != nil {
		t.Fatal(err)
	}
	if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}); !carried || err != nil {
		t.Fatal(carried, err)
	}
	record, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if record.Str("account") != "second" || file.Truthy("holds") {
		t.Fatal(run.Encode(record), run.Encode(file))
	}
}

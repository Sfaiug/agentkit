package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestReviewAccountRelaunchClearsTheKilledProcessesScreenHolds(t *testing.T) {
	home := accountHome(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), strings.ReplaceAll(testConfig, "harness='claude'", "harness='antigravity'")+"accounts=['default','second']\n")
	accountMeters(t, home, 100, 10)
	tray := "────────────────────────────────────────\n>\n────────────────────────────────────────\n● [12:08:46] sleep 45 running\n────────────────────────────────────────\n? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents · 1 task(s) · /tasks\n"
	drawn(t, home, "acme", tray)
	accountAdapter(t, home, "case \"$1\" in auth) exit 0 ;; interactive) echo 'sleep 600' ;; esac\n")
	if err := os.Rename(filepath.Join(home, "adapters", "claude.sh"), filepath.Join(home, "adapters", "antigravity.sh")); err != nil {
		t.Fatal(err)
	}
	if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}, false); !carried || err != nil {
		t.Fatalf("account relaunch not carried: %v, %v", carried, err)
	}
	record, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if record.Str("account") != "second" {
		t.Fatalf("account did not move: %s", run.Encode(record))
	}
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if file.Truthy("holds") {
		t.Fatalf("the replacement process inherited the killed process's screen holds: %s", run.Encode(file))
	}
}

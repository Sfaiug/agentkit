package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTheLastLookAtAGoneSeatFollowsItsLatestAnswer(t *testing.T) {
	// ses_Free's last answer ran on opencode/m-free at high (harness/testdata/opencode.db)
	readable, err := os.ReadFile(filepath.Join("..", "harness", "testdata", "opencode.db"))
	if err != nil {
		t.Fatal(err)
	}
	for name, database := range map[string]string{"readable": string(readable), "unreadable": "pages"} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"),
				opencodeConfig+"[models.free]\nharness='opencode'\nmodel='opencode/m-free'\neffort='low'\nprovider='test'\n")
			t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
			t.Setenv("OPENCODE_DB", "opencode.db")
			write(t, filepath.Join(home, "share", "opencode", "opencode.db"), database)
			token := strings.Repeat("a", 32)
			write(t, filepath.Join(stateFile(home, "opencode-launch-"+token), "session"), "ses_Free\n")
			record(t, home, "acme", map[string]any{"orchestrator": "vela", "workers": []string{"vela"},
				"opencode_launch": token, "id_source": nil})
			paneDied(t, "acme")
			seat, _, known := lookedAt(filepath.Join(home, ".agentkit", "state"), "acme", moment)
			if name == "unreadable" {
				if known {
					t.Fatal("a database that cannot be read was read as holding no answer")
				}
				return
			}
			if !known || seat.follow.chosen != "free" || seat.follow.effort != "high" {
				t.Fatalf("%v %+v", known, seat.follow)
			}
		})
	}
}

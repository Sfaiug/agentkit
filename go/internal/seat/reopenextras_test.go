package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestReopenKeepsHarnessLaunchEvidenceAndRestoresItOnRefusal(t *testing.T) {
	for _, outcome := range []string{"started", "refused"} {
		t.Run(outcome, func(t *testing.T) {
			home := sandbox(t)
			fakeTmux(t, home, "acme", true)
			if outcome == "started" {
				write(t, filepath.Join(home, "respawns"), "")
			}
			path := stateFile(home, "session-acme.json")
			write(t, path, `{"conversation":"conv-acme","id_source":"launcher","resumable":true,"account":"first","antigravity_launch":"old","antigravity_open":{"launch":"old","conversation":"conv-acme"}}`)
			before, _ := run.ReadJSON(path)
			rulebook := stateFile(home, "rulebook-acme.md")
			write(t, rulebook, "rules\n")
			back := reopening{name: "acme", held: true, account: "second", model: config.Model{Harness: "antigravity"}}
			_, err := back.launch(stateFile(home, ""), rulebook, []string{"antigravity"}, "conv-acme")
			if (err == nil) != (outcome == "started") {
				t.Fatal(outcome, err)
			}
			after, _ := run.ReadJSON(path)
			if outcome == "refused" {
				if !run.Equal(before, after) {
					t.Fatal("refused launch changed the record", after)
				}
				return
			}
			token := after.Str("antigravity_launch")
			if len(token) != 32 || after.Has("antigravity_open") || after.Str("conversation") != "conv-acme" || after.Str("account") != "second" {
				t.Fatal("reopen lost launch evidence or account", after)
			}
			files, _ := filepath.Glob(stateFile(home, "launch-acme.*"))
			if len(files) != 1 {
				t.Fatal("missing launch script", files)
			}
			script, err := os.ReadFile(files[0])
			if err != nil || !strings.Contains(string(script), "AGENTKIT_ANTIGRAVITY_LAUNCH="+token) {
				t.Fatal("harness did not receive its recorded launch token", string(script), err)
			}
		})
	}
}

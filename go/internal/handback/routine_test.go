//go:build unix

package handback

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestRoutineEndingsRecordOrRideWithoutTyping(t *testing.T) {
	for _, state := range []string{"not_needed", "pass"} {
		for _, route := range []string{"no plan", "finished plan", "riding", "ends wait"} {
			t.Run(state+"/"+route, func(t *testing.T) {
				home := seated(t)
				root := filepath.Join(home, ".agentkit")
				os.WriteFile(filepath.Join(root, "config.toml"), []byte("[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[models.astra]\nharness='codex'\nmodel='gpt'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n"), 0o600)
				os.WriteFile(filepath.Join(root, "state", "session-acme.json"), []byte(`{"orchestrator":"opus","workers":["opus","astra"],"conversation":"conv-acme","id_source":"launcher","cwd":"/acme","created":1}`), 0o600)
				plan := "- [ ] API ships\n"
				switch route {
				case "finished plan":
					plan = "- [x] API ships\n"
				case "riding":
					// another going run serves what the seat owes, so the ending ends no wait
					plan = "- [ ] API ships · check: `false` · acme · written 2026-10-23 09:00\n"
				}
				if route != "no plan" {
					os.WriteFile(filepath.Join(root, "state", "plan-acme.md"), []byte(plan), 0o600)
				}
				os.WriteFile(filepath.Join(home, "bin", "tmux"), []byte("#!/bin/sh\ncase \"$*\" in\n*list-sessions*) printf 'acme\\t1\\n';;\n*list-panes*) printf '0 1 %%1 0\\n';;\n*capture-pane*display-message*) printf '────────\\n❯\\n────────\\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\\n0\\n';;\n*capture-pane*) printf '────────\\n❯\\n────────\\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\\n';;\n*'#{pane_id}'*'#{session_created}'*) printf '%%1\\t123\\n';;\n*send-keys*) printf '%s\\n' \"$*\" >>\"$HOME/typed\"; exit 1;;\nesac\n"), 0o700)
				record := run.Fields("state", state, "run_id", "fix-api", "launched_session", "acme", "finished_at", now(),
					"not_needed", "already done", "merged", state == "pass", "pr", "https://github.com/acme/api/pull/1", "executor", "opus", "reviewer", "astra", "verdict", "PASS",
					"review", run.Fields("executor", "opus", "reviewer", "astra", "executor_provider", "test", "reviewer_provider", "test", "verdict", "PASS", "returncode", 0, "done_when", true))
				dir := filepath.Join(root, "runs", "fix-api")
				if err := os.MkdirAll(dir, 0o700); err != nil || run.Create(dir, record) != nil {
					t.Fatal(err)
				}
				if route == "riding" {
					other := filepath.Join(root, "runs", "other")
					os.MkdirAll(other, 0o700)
					run.Create(other, run.Fields("state", "running", "launched_session", "acme", "plan_line", "API ships · written 2026-10-23 09:00"))
				}
				Give(dir, nil, func(string) {})
				_, typed := os.Stat(filepath.Join(home, "typed"))
				if (typed == nil) != (route == "ends wait") {
					t.Fatalf("route %s attempted typing: %v", route, typed == nil)
				}
				after, _ := run.Read(dir)
				if route == "no plan" || route == "finished plan" {
					if !after.Truthy("handed_back") || after.Truthy("handback_pending") {
						t.Fatal("routine ending was not recorded", run.Line(after))
					}
				} else if !after.Truthy("handback_pending") {
					t.Fatal("undelivered ending lost its pending mark")
				}
			})
		}
	}
}

//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLookKeepsUntoldEndingsWorkingWithoutDeliveringThem(t *testing.T) {
	for _, state := range []string{"fail", "blocked", "pass"} {
		t.Run(state, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			write(t, stateFile(home, "plan-acme.md"), "- [x] API ships\n")
			path := runRecord(t, home, "fix-api", map[string]any{"state": state, "finished_at": float64(time.Now().Unix()), "started_at": 1, "tree_stopped": []any{nil, nil}, "no_merge": true})
			before, _ := os.ReadFile(path)
			bin := t.TempDir()
			write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$*\" in *'-L seat-test'*) ;; *) exit 1;; esac\ncase \"$*\" in\n*list-sessions*) printf 'acme\\t1\\n';;\n*list-panes*'#{session_name}'*) printf 'acme\\t0\\n';;\n*list-panes*) printf '0 1 %%1 0\\n';;\n*capture-pane*display-message*) printf '────────\\n❯\\n────────\\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\\n0\\n';;\n*capture-pane*) printf '────────\\n❯\\n────────\\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\\n';;\n*display-message*'#{session_attached}'*) printf '0\\n';;\n*) exit 0;;\nesac\n")
			os.Chmod(filepath.Join(bin, "tmux"), 0o700)
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			got, err := LookedLive(stateFile(home, ""), "acme")
			if err != nil || got.Word != "working" || got.reason != "telling it how run fix-api ended" {
				t.Fatalf("look lost an untold %s: word=%q, err=%v", state, got.Word, err)
			}
			if after, _ := os.ReadFile(path); string(after) != string(before) {
				t.Fatal("refused look changed the ending")
			}
		})
	}
}

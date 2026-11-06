//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestPendingAccountRecoveryReachesHealthBeforeHandingOverUnchanged(t *testing.T) {
	for _, field := range []string{"usage_wait", "usage_refusal", "midturn"} {
		t.Run(field, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			put(t, filepath.Join(ak, "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\naccounts=['default','second']\n")
			record := run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"}, "created", 1,
				"conversation", "conv-acme", "id_source", "launcher", "session_title", "acme"))
			path := filepath.Join(ak, "state", "session-acme.json")
			put(t, path, record)
			file := filepath.Join(ak, "state", "seat-acme.json")
			pending := run.Line(run.Fields(field, run.Fields("account", true, "since", 1)))
			put(t, file, pending)
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in '-L tick-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *'#{pane_id} #{pane_dead}'*) printf '%%1 0\n' ;;
  *list-panes*) printf 'acme\t0\n' ;;
  *capture-pane*) printf '────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n' ;;
  *session_attached*) printf '0\t%%1\t%s\n' "$HOME" ;;
  *show-options*) echo %1 ;;
  *display-message*) echo acme ;;
esac
`)
			if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
				t.Fatal(err)
			}
			tick := checking(t, io.Discard)
			reached := false
			rows := table(tick)
			for i, row := range rows {
				if row.name == "seat health" {
					rows[i].step = func() error { reached = true; return row.step() }
					rows = rows[:i+1]
					break
				}
			}
			if tick.through(rows) || !reached || read(t, path) != record || read(t, file) != pending {
				t.Fatal("pending recovery was decided early or rewritten")
			}
		})
	}
}

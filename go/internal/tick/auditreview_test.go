//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestReviewAuditSeatDiesWithTypedLine(t *testing.T) {
	for _, death := range []string{"gone", "exited"} {
		t.Run(death, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			home := os.Getenv("HOME")
			t.Setenv("REVIEW_DEATH", death)
			bin := filepath.Join(home, "bin")
			put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*)
    if [ "$REVIEW_DEATH" = gone ] && [ ! -e "$HOME/resumed" ]; then
      [ ! -e "$HOME/seat-observed" ] || exit 0
      touch "$HOME/seat-observed"
    fi
    printf 'audit\t1\n' ;;
  *list-panes*)
    if [ "$REVIEW_DEATH" = exited ] && [ ! -e "$HOME/resumed" ]; then
      if [ -e "$HOME/panes-observed" ]; then
        printf 'audit\t1\n'
      else
        touch "$HOME/panes-observed"
        printf 'audit\t0\n'
      fi
    else
      printf 'audit\t0\n'
    fi ;;
  *new-session*|*respawn-pane*) touch "$HOME/resumed" ;;
  *show-options*) printf '%%1\n' ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1\n' ;;
  *display-message*'#{session_name}'*) printf 'audit\n' ;;
  *capture-pane*) cat "$HOME/prompt" ;;
  *send-keys*) touch "$HOME/keys-sent" ;;
esac
`)
			put(t, filepath.Join(bin, "claude"), "#!/bin/sh\nexit 0\n")
			adapters := t.TempDir()
			put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\nprintf 'claude --resume conv-audit\\n'\n")
			for _, path := range []string{filepath.Join(bin, "tmux"), filepath.Join(bin, "claude"), filepath.Join(adapters, "claude.sh")} {
				if err := os.Chmod(path, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
			cwd := filepath.Join(home, "work")
			if err := os.MkdirAll(cwd, 0o700); err != nil {
				t.Fatal(err)
			}
			put(t, filepath.Join(ak, "state", "session-audit.json"), `{"orchestrator":"opus","workers":["opus"],"cwd":"`+cwd+`","repo":null,"conversation":"conv-audit","id_source":"launcher"}`)
			put(t, filepath.Join(home, "prompt"), read(t, filepath.Join(config.Repo(), "tests", "fixtures", "claude-prompt-pane.txt")))
			path := filepath.Join(ak, "state", "audit.json")
			before := `{"week":"2026-W45","line":"earlier work","typed":{"line":"earlier work","seat":1},"delivered":null}`
			put(t, path, before)
			tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
			err := tick.audit()
			_, resumed := os.Stat(filepath.Join(home, "resumed"))
			if resumed == nil {
				t.Error("resumed a seat that died while its typed line was undelivered")
			}
			if !errors.Is(err, errLeft) || read(t, path) != before {
				t.Errorf("the dead seat's typed line was not handed to Python: err=%v state=%s", err, read(t, path))
			}
			if death == "exited" && resumed == nil {
				if err := tick.audit(); err != nil {
					t.Fatal(err)
				}
				state, err := run.ReadJSON(path)
				if err != nil {
					t.Fatal(err)
				}
				if _, sent := os.Stat(filepath.Join(home, "keys-sent")); state.Truthy("delivered") && os.IsNotExist(sent) {
					t.Error("the replacement harness received no keys, but the lost line was marked delivered")
				}
			}
		})
	}
}

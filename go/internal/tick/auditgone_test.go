//go:build unix

package tick

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A line typed into an audit seat that is not up is delivered at least once and typed into no one
// composer twice: a new harness, in a new session or a dead pane respawned in place under the
// seat's birth, takes the line again once it sits at its quiet prompt, an earlier week's before
// this week's is written, and a seat that one tmux lookup missed is attached again and keeps the
// receipt of its line sent.
func TestAGoneAuditSeatGetsItsTypedLine(t *testing.T) {
	const earlier, now = "ak's week 2026-W44: an earlier loss", "ak's week 2026-W45: this loss"
	const prompt = "────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
	// each is a seat whose session is gone, whose harness exited (dead) or that one lookup missed,
	// holding a week's line typed and undelivered, its last screen, how it is started, and the lines
	// its composers take, this week's as the tick writes it after them where it is written
	for _, each := range []struct {
		name, week, line, look, shown, started string
		typed                                  []string
		written                                bool
	}{
		{"resumed, then delivered", "2026-W45", now, "gone", strings.Replace(prompt, "❯", "❯ "+now, 1), "new-session\n", []string{now}, false},
		{"no week lost", "2026-W44", earlier, "dead", strings.Replace(prompt, "❯", "❯ "+earlier, 1), "respawn-pane\n", []string{earlier}, true},
		{"no line twice", "2026-W45", now, "missed", prompt, "", nil, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			home := filepath.Dir(ak)
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			draw := `printf '────────\n❯%s\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n'`
			// a start keeps the seat's birth, 1000, gives its pane another process, and draws
			// nothing while its harness comes up
			put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
dead() { if [ -e "$HOME/dead" ]; then echo 1; else echo 0; fi; }
case "$*" in
  *respawn-pane*) echo respawn-pane >> "$HOME/started"; echo 2 > "$HOME/pid"; rm -f "$HOME/dead"; : > "$HOME/shown" ;;
  *new-session*) echo new-session >> "$HOME/started"; echo 2 > "$HOME/pid"; rm -f "$HOME/gone"; : > "$HOME/shown" ;;
  *list-sessions*) if [ -e "$HOME/missed" ]; then rm "$HOME/missed"; exit 1; fi; [ -e "$HOME/gone" ] || printf 'audit\t1\n' ;;
  *list-panes*'#{pane_id} #{pane_dead}'*) printf '%%1 %s\n' "$(dead)" ;;
  *list-panes*) printf 'audit\t%s\n' "$(dead)" ;;
  *show-options*) echo %1 ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\t%s\n' "$(cat "$HOME/pid" 2>/dev/null || echo 1)" ;;
  *display-message*session_path*) printf '%s\t1000\n' "$HOME" ;;
  *display-message*session_name*) echo audit ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then `+draw+` "" > "$HOME/shown"; else `+draw+` " $last" > "$HOME/shown"; fi ;;
esac
`)
			repo, err := filepath.Abs("../../..")
			if err != nil {
				t.Fatal(err)
			}
			put(t, filepath.Join(bin, "git"), fmt.Sprintf("#!/bin/sh\nprintf '%%s\\n' %q\n", repo))
			adapters := t.TempDir()
			put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\necho /bin/true\n")
			for _, path := range []string{filepath.Join(bin, "tmux"), filepath.Join(bin, "git"), filepath.Join(adapters, "claude.sh")} {
				if err := os.Chmod(path, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			cwd := filepath.Join(home, "work", "audit")
			if err := os.MkdirAll(cwd, 0o700); err != nil {
				t.Fatal(err)
			}
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n"+
				"[providers.test]\nmode='subscription'\n")
			put(t, filepath.Join(ak, "state", "session-audit.json"), run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"},
				"conversation", "conv-audit", "id_source", "launcher", "resumable", true, "cwd", cwd)))
			put(t, filepath.Join(home, each.look), "")
			put(t, filepath.Join(home, "shown"), each.shown)
			path := filepath.Join(ak, "state", "audit.json")
			// typed into the harness that went: the seat's birth, the pane's first process
			put(t, path, run.Line(run.Fields("week", each.week, "line", each.line, "typed", run.Fields("line", each.line, "seat", 1000, "pid", 1), "delivered", nil)))
			tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
			tick.report = func(time.Time) ([]string, string) { return nil, "fixture loss" }
			pass := func() *run.Object {
				t.Helper()
				if err := tick.audit(); err != nil {
					t.Fatal(err)
				}
				state, _ := run.ReadJSON(path)
				return state
			}

			// the seat comes back with its line still to be told, and a new harness not yet at its
			// prompt takes nothing
			untold := func() {
				t.Helper()
				if state := pass(); state.Str("week") != each.week || state.Str("line") != each.line || !state.Truthy("typed") || state.Truthy("delivered") || typedKeys(t, home) != nil {
					t.Fatalf("delivered before a composer took the line: %s, typed %q", run.Line(state), typedKeys(t, home))
				}
			}
			untold()
			if each.started != "" {
				untold()
				put(t, filepath.Join(home, "shown"), prompt)
			}
			var state *run.Object
			for range 3 {
				state = pass()
			}
			if state.Str("week") != "2026-W45" || !state.Truthy("delivered") {
				t.Fatalf("this week's line is not delivered: %s", run.Line(state))
			}
			if started, _ := os.ReadFile(filepath.Join(home, "started")); string(started) != each.started {
				t.Fatalf("started %q, not %q", started, each.started)
			}
			if each.written {
				each.typed = append(each.typed, state.Str("line"))
			}
			var want []string
			for _, line := range each.typed {
				want = append(want, line, "Enter")
			}
			if got := typedKeys(t, home); !slices.Equal(got, want) {
				t.Fatalf("typed %q, not %q", got, want)
			}
		})
	}
}

// typedKeys are those the fake tmux took, in order.
func typedKeys(t *testing.T, home string) []string {
	t.Helper()
	typed, err := os.ReadFile(filepath.Join(home, "keys"))
	if os.IsNotExist(err) {
		return nil
	} else if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(typed), "\n"), "\n")
}

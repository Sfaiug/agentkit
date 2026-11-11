//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// No home here stores a lineup, so the model list turns nothing off (matrix.Off).
func init() { ModelOff = func(string) (bool, error) { return false, nil } }

func moveHome(t *testing.T) string {
	t.Helper()
	home := sandbox(t)
	fakeTmux(t, home, "acme", false)
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"fake/git":   "#!/bin/sh\nprintf '%s\\n' '" + repo + "'\n",
		"fake/codex": "#!/bin/sh\nexit 0\n", "fake/claude": "#!/bin/sh\nexit 0\n",
		"adapters/codex.sh": `#!/bin/sh
case "$1" in
auth) [ "$2" = seat ] && [ "$MOVE_AUTH" != no ] || { echo 'login missing'; exit 1; }; echo 'signed in' ;;
interactive) case "$*" in *' new') exit 3 ;; esac; printf '%s\n' "$AGENTKIT_FIRST_PROMPT" > "$HOME/first-prompt"; echo '/bin/true' ;;
esac
`,
		"fake/tmux": `#!/bin/sh
case "$*" in
  *respawn-pane*) cat "$HOME/.agentkit/state/session-acme.json" > "$HOME/at-launch"; [ -e "$HOME/respawns" ] ;;
  *list-sessions*) printf 'acme\t1\n' ;;
  *capture-pane*display-message*) [ ! -f "$HOME/screen" ] || cat "$HOME/screen"; printf '\n%s\n' "${MOVE_PANE_DEAD:-0}" ;;
  *'#{pane_dead}') printf '%s\n' "$MOVE_PANE_DEAD" ;;
  *list-panes*) printf 'acme\t0\n' ;;
  *capture-pane*) [ ! -f "$HOME/screen" ] || cat "$HOME/screen" ;;
  *show-options*) echo '%1' ;;
  *display-message*) echo acme ;;
esac
`,
	}
	files["adapters/claude.sh"] = files["adapters/codex.sh"]
	for path, content := range files {
		path = filepath.Join(home, path)
		write(t, path, content)
		if err := os.Chmod(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", filepath.Join(home, "adapters"))
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("MOVE_AUTH", "yes")
	t.Setenv("MOVE_PANE_DEAD", "0")
	record(t, home, "acme", map[string]any{"orchestrator": "fable", "workers": []string{"astra"}})
	if err := os.MkdirAll(filepath.Join(home, "work", "acme"), 0o700); err != nil {
		t.Fatal(err)
	}
	return home
}

func TestMoveKeepsEscAndHandsUnsupportedSeatsBackBeforeAsking(t *testing.T) {
	for _, scenario := range []string{"esc", "fresh restart", "login", "spent session", "not installed", "kept conversation", "remote cleanup", "draft", "dialog"} {
		t.Run(scenario, func(t *testing.T) {
			home := moveHome(t)
			model := "astra"
			switch scenario {
			case "login":
				t.Setenv("MOVE_AUTH", "no")
			case "spent session":
				write(t, stateFile(home, "usage.json"), `{"providers":{"test":{"meters":[{"name":"session","window_secs":18000,"used":100}]}}}`)
			case "not installed":
				os.Remove(filepath.Join(home, "fake", "codex"))
				t.Setenv("PATH", filepath.Join(home, "fake"))
			case "remote cleanup":
				model = "fable"
				record(t, home, "acme", map[string]any{"orchestrator": "astra"})
				write(t, stateFile(home, "codex-remote-acme.forgotten"), "")
			case "kept conversation", "fresh restart":
				model = "opus"
				if scenario != "kept conversation" {
					record(t, home, "acme", map[string]any{"orchestrator": "fable", "conversation": nil})
				}
				t.Setenv("MOVE_PANE_DEAD", "1")
			case "draft", "dialog":
				fixture := "claude-draft-pane.txt"
				if scenario == "dialog" {
					fixture = "claude-permission-pane.txt"
				}
				text, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", fixture))
				if err != nil {
					t.Fatal(err)
				}
				write(t, filepath.Join(home, "screen"), string(text))
			}
			state := filepath.Join(home, ".agentkit", "state")
			before, _ := os.ReadFile(stateFile(home, "session-acme.json"))
			asked, kept := false, false
			known, err := Move("acme", model, "", func(keeps bool) (bool, bool) { asked, kept = true, keeps; return false, true })
			confirm := scenario == "esc" || scenario == "fresh restart" || scenario == "kept conversation"
			if err != nil || known != confirm || asked != confirm || kept != (scenario == "kept conversation") {
				t.Fatalf("known=%v, asked=%v, kept=%v, err=%v", known, asked, kept, err)
			}
			after, _ := os.ReadFile(stateFile(home, "session-acme.json"))
			entries, _ := os.ReadDir(state)
			want := 1
			if scenario == "spent session" || scenario == "remote cleanup" {
				want++
			}
			if string(after) != string(before) || len(entries) != want {
				t.Fatalf("an unaccepted move wrote state: %s, %v", after, entries)
			}
		})
	}
}

func TestMoveUsesReopenAndRestoresARefusedRestart(t *testing.T) {
	for _, start := range []bool{false, true} {
		t.Run(map[bool]string{false: "refused", true: "started"}[start], func(t *testing.T) {
			home := moveHome(t)
			state := filepath.Join(home, ".agentkit", "state")
			if start {
				write(t, filepath.Join(home, "respawns"), "")
			}
			write(t, stateFile(home, "handover-acme.md"), "earlier\n")
			write(t, stateFile(home, "hook-acme.json"), `{"event":"Stop"}`)
			write(t, stateFile(home, "seat-acme.json"), `{"usage_wait":{"continue":true},"unasked":{"text":"old question"}}`)
			write(t, stateFile(home, "watch.json"), `{"seen_at":{"acme":1,"other":2},"stalls":{"acme":{"at":1},"other":{"at":2}}}`)
			before, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			_, record, _ := config.ResolveSession("acme")
			path, _ := harness.Conversation("claude", record)
			write(t, path, "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"keep working\"}}\n")
			known, err := Move("acme", "astra", "", func(bool) (bool, bool) {
				// A concurrent mark survives the move's update under Python's lock.
				if err := update(state, "acme", set([]field{{"reviewers", []any{"fable"}}})); err != nil {
					t.Fatal(err)
				}
				return true, true
			})
			if !known || (err == nil) != start {
				t.Fatal(known, err)
			}
			after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			handed, _ := os.ReadFile(stateFile(home, "handover-acme.md"))
			watch, _ := run.ReadJSON(stateFile(home, "watch.json"))
			if run.Line(after.Get("reviewers")) != `["fable"]` {
				t.Fatal("lost concurrent marks", run.Line(after))
			}
			if !start {
				after.Delete("reviewers")
				if !run.Equal(before, after) || string(handed) != "earlier\n" || watch.Dict("stalls").Dict("acme") == nil {
					t.Fatal("a refused move changed the seat", run.Line(after), string(handed), run.Line(watch))
				}
				if receipts, _ := filepath.Glob(filepath.Join(state, "codex-launch-*.json")); len(receipts) != 0 {
					t.Fatal("a refused launch left receipts", receipts)
				}
				return
			}
			launched, _ := run.ReadJSON(filepath.Join(home, "at-launch"))
			if launched.Str("orchestrator") != "astra" || launched.Str("codex_launch") == "" || after.Has("conversation") ||
				after.Get("resumable") != false || after.Get("launched") == nil {
				t.Fatal("launch did not own the new model first", run.Line(launched), run.Line(after))
			}
			if string(handed) != "earlier\n## Its conversation on fable\n\n**user:** keep working\n\n" ||
				watch.Dict("stalls").Has("acme") || !watch.Dict("stalls").Has("other") {
				t.Fatal("handover or watch reset differs", string(handed), run.Line(watch))
			}
			file := revivalFile("acme")
			prompt, _ := os.ReadFile(filepath.Join(home, "first-prompt"))
			if file.Get("usage_wait") != nil || file.Get("unasked") != nil || file.Dict("midturn").Str("line") != movedLine ||
				file.Dict("midturn").Get("launched") != true || strings.TrimSpace(string(prompt)) != movedLine {
				t.Fatal("continuation differs", run.Line(file), string(prompt))
			}
			// the first prompt is ak's, never the owner's (receipted)
			if typed, _ := os.ReadFile(ownFile("input", "acme")); !strings.Contains(string(typed), `"text": `+run.Line(movedLine)+`, "source": "ak"`) {
				t.Fatal("no typing receipt for the first prompt", string(typed))
			}
		})
	}
}

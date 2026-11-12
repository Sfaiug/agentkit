//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// A seat restarted on its own harness, at a step its running harness cannot take, goes on in the
// conversation it owns: asked so, resumed on it at the step, handed nothing and forgetting nothing,
// and a turn its usage cut off told to go on in it as a reopened seat's is.
func TestARestartOnItsOwnHarnessGoesOnInItsConversation(t *testing.T) {
	home := moveHome(t)
	t.Setenv("MOVE_PANE_DEAD", "1") // its harness ended: nothing types the step into it
	write(t, filepath.Join(home, "respawns"), "")
	write(t, filepath.Join(home, "adapters", "claude.sh"), `#!/bin/sh
case "$1" in
auth) echo 'signed in' ;;
interactive) printf '%s\n' "$*" > "$HOME/interactive"; printf '%s\n' "$AGENTKIT_FIRST_PROMPT" > "$HOME/first-prompt"; echo /bin/true ;;
esac
`)
	write(t, stateFile(home, "handover-acme.md"), "earlier\n")
	write(t, stateFile(home, "seat-acme.json"), `{"usage_wait":{"continue":true}}`)
	write(t, stateFile(home, "watch.json"), `{"stalls":{"acme":{"at":1}}}`)
	_, record, _ := config.ResolveSession("acme")
	path, _ := harness.Conversation("claude", record)
	write(t, path, "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"keep working\"}}\n")
	asked := 0
	known, err := Move("acme", "fable", "max", func(kept bool) (bool, bool) {
		if !kept {
			t.Error("the card says its conversation ends")
		}
		asked++
		return true, true
	})
	if !known || err != nil || asked != 1 {
		t.Fatal(known, err, asked)
	}
	argv, _ := os.ReadFile(filepath.Join(home, "interactive"))
	prompt, _ := os.ReadFile(filepath.Join(home, "first-prompt"))
	if strings.TrimSpace(string(argv)) != "interactive claude-fable max conv-acme" || strings.TrimSpace(string(prompt)) != MidturnContinue {
		t.Fatalf("not resumed on its conversation at the step: %q, %q", argv, prompt)
	}
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if after.Str("conversation") != "conv-acme" || after.Dict("efforts").Dict("fable").Str("effort") != "max" || after.Has("left") {
		t.Fatal("the record differs", run.Line(after))
	}
	handed, _ := os.ReadFile(stateFile(home, "handover-acme.md"))
	watch, _ := run.ReadJSON(stateFile(home, "watch.json"))
	if string(handed) != "earlier\n" || !watch.Dict("stalls").Has("acme") {
		t.Fatal("a kept conversation was handed over or forgotten", string(handed), run.Line(watch))
	}
	if mark := revivalFile("acme").Dict("midturn"); mark.Str("line") != MidturnContinue || mark.Get("launched") != true {
		t.Fatal("the turn is not told to go on", run.Line(mark))
	}
}

// openCodeSeat is moveHome's seat on an OpenCode model, its adapter taking `none` only from a
// launch and running `during` as it is asked for one; then the file by which its launch names its
// conversation.
func openCodeSeat(t *testing.T, during string) (string, string) {
	home := moveHome(t)
	database, _ := filepath.Abs(filepath.Join("..", "harness", "testdata", "opencode.db"))
	t.Setenv("OPENCODE_DB", database)
	config := filepath.Join(home, ".agentkit", "config.toml")
	text, _ := os.ReadFile(config)
	write(t, config, string(text)+"[models.spark]\nharness='opencode'\nmodel='opencode/acme'\neffort='max'\nprovider='test'\n")
	for path, content := range map[string]string{"fake/opencode": "#!/bin/sh\nexit 0\n", "adapters/opencode.sh": `#!/bin/sh
case "$1" in
auth) echo 'signed in' ;;
variants) echo '{"provider": {"opencode": {"models": {"acme": {"variants": {"none": {}}}}}}}' ;;
interactive) ` + during + `; echo /bin/true ;;
esac
`} {
		write(t, filepath.Join(home, path), content)
		if err := os.Chmod(filepath.Join(home, path), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	token := strings.Repeat("d", 32)
	record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"astra"}, "opencode_launch": token,
		"conversation": nil, "id_source": nil, "resumable": nil})
	return home, stateFile(home, "opencode-launch-"+token+"/session")
}

// A line ak typed before OpenCode named its conversation stays ak's once the restart retires the
// launch that named it (nameReceipts).
func TestARestartKeepsWhoseLinesItsConversationHolds(t *testing.T) {
	home, session := openCodeSeat(t, ":")
	t.Setenv("MOVE_PANE_DEAD", "1")
	write(t, filepath.Join(home, "respawns"), "")
	_, record, _ := config.ResolveSession("acme")
	sent, err := typingReceipt("opencode", record, "Rename the acme report.")
	if err != nil {
		t.Fatal(err)
	}
	write(t, ownFile("input", "acme"), run.Line(sent)+"\n")
	write(t, session, "ses_Free") // its one user row (harness/testdata/opencode.db)
	known, err := Move("acme", "spark", "none", func(bool) (bool, bool) { return true, true })
	if !known || err != nil {
		t.Fatal(known, err)
	}
	if conversation, said, err := notify.OwnerMessages("acme"); conversation != "ses_Free" || len(said) != 0 || err != nil {
		t.Fatalf("ak's own line reads as the owner's: %s, %v, %v", conversation, said, err)
	}
}

// Text typed into the seat's composer while its adapter prepared the launch refuses the restart,
// which would discard it.
func TestARestartRefusesADraftTypedMeanwhile(t *testing.T) {
	home, session := openCodeSeat(t, `cp "$HOME/draft" "$HOME/screen"`)
	write(t, session, "ses_Free")
	write(t, filepath.Join(home, "respawns"), "")
	prompt, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", "opencode-prompt-pane.txt"))
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(home, "screen"), string(prompt))
	write(t, filepath.Join(home, "draft"), strings.Replace(string(prompt), `Ask anything… "What is the tech stack of this project?"`, "keep this", 1))
	before, _ := os.ReadFile(stateFile(home, "session-acme.json"))
	known, err := Move("acme", "spark", "none", func(bool) (bool, bool) { return true, true })
	if !known || err != screenChanged {
		t.Fatal(known, err)
	}
	after, _ := os.ReadFile(stateFile(home, "session-acme.json"))
	if _, respawned := os.Stat(filepath.Join(home, "at-launch")); respawned == nil || string(after) != string(before) {
		t.Fatalf("restarted over the draft: %s", after)
	}
}

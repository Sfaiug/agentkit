package transcript

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAConversationsEndReadsThroughItsHarnesssManifest(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	said := func(text string) string {
		return `{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hm"}, {"type": "text", "text": "` + text + `"}]}}`
	}
	prompt := `{"type": "user", "timestamp": "2026-10-31T05:00:00.5Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "go"}}`
	const at = 1793422800.5
	card := `{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": "AskUserQuestion"}]}}`
	answer := `{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Yes"}]}}`
	// a line past the first read back, which the next read ends
	filler := `{"type": "progress", "data": "` + strings.Repeat("x", 600<<10) + `"}`
	for _, each := range []struct {
		name  string
		lines []string
		want  End
	}{
		{"the newest words, a sub-agent's aside", []string{prompt, said("Merged."),
			`{"type": "assistant", "isSidechain": true, "message": {"content": [{"type": "text", "text": "Mine?"}]}}`},
			End{Said: "Merged.", Prompted: at}},
		{"words a turn before", []string{said("Merge it?"), prompt, card, answer}, End{Said: "Merge it?", Prompted: at}},
		{"a card unanswered", []string{prompt, said("Merge it?"), card}, End{Said: "Merge it?", Asking: true}},
		{"a card answered", []string{prompt, card, answer, said("Merged.")}, End{Said: "Merged.", Prompted: at}},
		{"a card before the owner's prompt", []string{card, prompt, said("Merged.")}, End{Said: "Merged.", Prompted: at}},
		{"the harness's own lines and bookkeeping", []string{prompt,
			`{"type": "user", "message": {"role": "user", "content": "<command-name>/model</command-name>"}}`,
			`{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}`,
			`{"type": "user", "isMeta": true, "message": {"role": "user", "content": "rules"}}`,
			`{"type": "user", "origin": {"kind": "task-notification"}, "message": {"role": "user", "content": "done"}}`,
			said("Merged.")}, End{Said: "Merged.", Prompted: at}},
		{"a prompt queued while the turn ran", []string{said("Merged."), `{"type": "attachment", "timestamp": 7, "attachment": ` +
			`{"type": "queued_command", "prompt": "and the docs", "origin": {"kind": "human"}}}`}, End{Said: "Merged.", Prompted: 7}},
		{"read back past a long line", []string{prompt, filler, said("Merge it?")}, End{Said: "Merge it?", Prompted: at}},
	} {
		path := filepath.Join(t.TempDir(), "conversation.jsonl")
		if err := os.WriteFile(path, []byte(strings.Join(each.lines, "\n")+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		if got := Read("claude", path); got != each.want {
			t.Errorf("%s: %+v, want %+v", each.name, got, each.want)
		}
	}
	if got := Read("acme", ""); got != (End{}) {
		t.Errorf("a harness with no table reads %+v", got)
	}
}

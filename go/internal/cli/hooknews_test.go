package cli

import (
	"testing"

	"agentkit/internal/run"
)

// A slash command and a turn the harness begins on finished work answer nothing.
func TestOwnersWords(t *testing.T) {
	for payload, want := range map[string]string{
		`{"prompt": "the new one"}`:               "the new one",
		`{"message": "from a notice"}`:            "from a notice",
		`{"prompt": 7, "message": "words"}`:       "words",
		`{}`:                                      "",
		`{"prompt": "see /tmp and /usr"}`:         "see /tmp and /usr",
		`{"prompt": " /Users/acme/a.pdf"}`:        " /Users/acme/a.pdf",
		`{"prompt": "/"}`:                         "/",
		`{"prompt": "go", "prompt_id": "task-1"}`: "go",
	} {
		read, _ := run.Decode([]byte(payload))
		if got := ownersWords(read.(*run.Object)); got == nil || *got != want {
			t.Errorf("%s: %v, want %q", payload, got, want)
		}
	}
	for _, payload := range []string{`{"prompt": "/compact"}`, `{"prompt": " \n/model opus"}`, `{"message": "/compact"}`, `{"prompt": "/help /Users/acme/a.pdf"}`,
		`{"prompt": "go", "message": "/compact"}`, `{"prompt": "<task-notification>done"}`, `{"prompt": "a <task-notification> within"}`,
		`{"prompt": " <system-reminder>later"}`, `{"prompt": "go", "prompt_id": "task-completed-1"}`,
		`{"prompt": "go", "promptId": "subagent-completed-1"}`} {
		read, _ := run.Decode([]byte(payload))
		if got := ownersWords(read.(*run.Object)); got != nil {
			t.Errorf("%s: %q, want no owner", payload, *got)
		}
	}
}

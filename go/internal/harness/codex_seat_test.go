package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Codex runs a command-line hook only once its hash is trusted: the trust is codex.py's `trust`,
// word for word.
func TestCodexHooksAreTrustedAsPythonTrustsThem(t *testing.T) {
	flags := codexHookFlags("/acme/go/bin/ak")
	if len(flags) != 2*(len(codexHooks)+1) || flags[1] != `hooks.SessionStart=[{hooks=[{type="command",command="/acme/go/bin/ak adapter /acme/go codex hook",timeout=600}]}]` ||
		flags[11] != `hooks.PreToolUse=[{matcher="request_user_input(_async)?",hooks=[{type="command",command="/acme/go/bin/ak adapter /acme/go codex hook",timeout=600}]}]` {
		t.Fatalf("hooks: %q", flags)
	}
	const python = `hooks.state={"/<session-flags>/config.toml:session_start:0:0"={trusted_hash="sha256:b63abd040056283f3ac2bd9b6eed755ed8a53175c8c7c4adac0d934354854524"},"/<session-flags>/config.toml:user_prompt_submit:0:0"={trusted_hash="sha256:75be625f00ea1f15fdc81ded77ef96a135380a6f5340d28d7c0285098c2154d3"},"/<session-flags>/config.toml:stop:0:0"={trusted_hash="sha256:8cd866a102fd4c1078c7f45bbf110ada6a51e002bafc1d53e6ef568846e60ba6"},"/<session-flags>/config.toml:interrupt:0:0"={trusted_hash="sha256:3d5a760bbeaa287855caf083db15e043d829343bd4e9ff478720c8ff82afe5fc"},"/<session-flags>/config.toml:permission_request:0:0"={trusted_hash="sha256:73927f80d7f7a6c6ef9ea0e2298fa1ffcb79ecf497113757458c04e598ff95b1"},"/<session-flags>/config.toml:pre_tool_use:0:0"={trusted_hash="sha256:65d56aae7eca89b1d7dd04fef230444cea4eeb12d9c6b66d1d5625b394b933af"},"/<session-flags>/config.toml:post_tool_use:0:0"={trusted_hash="sha256:86eefca9204fc6e7cbf15aa7971ddd6713e1314646ee29b0785a49a4befd2e61"}}`
	if got := flags[len(flags)-1]; got != python {
		t.Fatalf("trust:\n%s\nwant\n%s", got, python)
	}
}

// The line is adapters/codex.sh's, Go's wrapper in tools/codex-seat.py's place.
func TestCodexSeatLine(t *testing.T) {
	rulebook := filepath.Join(t.TempDir(), "rulebook.md")
	os.WriteFile(rulebook, []byte("rules"), 0o600)
	t.Setenv("AGENTKIT_RULEBOOK", rulebook)
	t.Setenv("AGENTKIT_ACCOUNT", "")
	t.Setenv("AGENTKIT_FIRST_PROMPT", "-v it's on")
	head := "env AGENTKIT_RULEBOOK=" + rulebook + " /acme/bin/ak adapter /acme codex seat -- codex "
	for _, each := range []struct {
		args []string
		code int
		line string
	}{
		{[]string{"gpt-6-astra", "xhigh"}, 0, head + `--yolo -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' -c project_doc_max_bytes=0 -- '-v it'"'"'s on'`},
		{[]string{"default", "low", "thread-1"}, 0, head + `resume thread-1 --yolo -c 'model_reasoning_effort="low"' -c project_doc_max_bytes=0 -- '-v it'"'"'s on'`},
		{[]string{"gpt-6-astra", "xhigh", "thread-1", "new"}, 3, ""},
		{[]string{"gpt-6-astra", "x high"}, 2, ""},
	} {
		var out bytes.Buffer
		if code := codexInteractive("/acme", each.args, &out, new(bytes.Buffer)); code != each.code || strings.TrimSuffix(out.String(), "\n") != each.line {
			t.Errorf("%q: exit %d\n%s", each.args, code, out.String())
		}
	}
	t.Setenv("AGENTKIT_ACCOUNT", "work")
	if code := codexInteractive("/acme", []string{"gpt-6-astra", "xhigh"}, new(bytes.Buffer), new(bytes.Buffer)); code != 2 {
		t.Errorf("an account's seat is Python's: exit %d", code)
	}
}

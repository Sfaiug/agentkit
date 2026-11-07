package harness

import (
	"bufio"
	"bytes"
	"io"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
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
	home := t.TempDir()
	t.Setenv("HOME", home)
	rulebook := filepath.Join(t.TempDir(), "rulebook.md")
	os.WriteFile(rulebook, []byte("rules"), 0o600)
	t.Setenv("AGENTKIT_RULEBOOK", rulebook)
	t.Setenv("AGENTKIT_ACCOUNT", "")
	// the usual login's, under the account home a seat on one handed down
	t.Setenv("CODEX_HOME", home+"/.codex-second")
	t.Setenv("AGENTKIT_FIRST_PROMPT", "-v it's on")
	head := "env CODEX_HOME=" + home + "/.codex AGENTKIT_RULEBOOK=" + rulebook + " /acme/bin/ak adapter /acme codex seat -- codex "
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
	// an account's, in its own Codex home, which shares the usual one's conversations and config
	t.Setenv("AGENTKIT_ACCOUNT", "work")
	os.MkdirAll(filepath.Join(home, ".codex"), 0o700)
	os.WriteFile(filepath.Join(home, ".codex", "config.toml"), nil, 0o600)
	var out bytes.Buffer
	if code := codexInteractive("/acme", []string{"gpt-6-astra", "xhigh"}, &out, new(bytes.Buffer)); code != 0 ||
		out.String() != "env -u OPENAI_API_KEY -u CODEX_API_KEY CODEX_HOME="+home+"/.codex-work AGENTKIT_RULEBOOK="+rulebook+
			` /acme/bin/ak adapter /acme codex seat -- codex --yolo -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' -c project_doc_max_bytes=0 -- '-v it'"'"'s on'`+"\n" {
		t.Errorf("an account's seat: exit %d\n%s", code, out.String())
	}
	for _, name := range []string{"sessions", "archived_sessions", "config.toml"} {
		if to, err := os.Readlink(filepath.Join(home, ".codex-work", name)); err != nil || to != filepath.Join(home, ".codex", name) {
			t.Errorf("%s: %q, %v", name, to, err)
		}
	}
}

// A Codex an installer put in a folder no fresh shell has on PATH is asked about hooks too, as the
// seat finds it to run.
func TestCodexHookSupportIsAskedOfTheCodexTheSeatRuns(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake Codex is a shell script")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	codex := filepath.Join(home, ".npm-global", "bin", "codex")
	os.MkdirAll(filepath.Dir(codex), 0o700)
	os.WriteFile(codex, []byte("#!/bin/sh\necho '  --dangerously-bypass-hook-trust'\n"), 0o700)
	if !codexHooked("codex", os.Environ()) {
		t.Fatal("the Codex in ~/.npm-global/bin was not asked")
	}
}

// A server's ping is answered with its own payload, as a WebSocket peer must.
func TestCodexClientAnswersAPingWithItsPayload(t *testing.T) {
	conn, server := net.Pipe()
	defer conn.Close()
	defer server.Close()
	server.SetDeadline(time.Now().Add(5 * time.Second))
	conn.SetDeadline(time.Now().Add(5 * time.Second))
	pong := make(chan []byte, 1)
	go func() {
		defer close(pong)
		server.Write([]byte{0x89, 3, 'a', 'k', '?'})
		frame := make([]byte, 2+4+3)
		if _, err := io.ReadFull(server, frame); err != nil || frame[0] != 0x8a || frame[1] != 0x80|3 {
			return
		}
		for i := range 3 {
			frame[6+i] ^= frame[2+i%4]
		}
		pong <- frame[6:]
		server.Write([]byte{0x81, 2, '{', '}'})
	}()
	client := codexClient{conn: conn, read: bufio.NewReader(conn)}
	if _, err := client.receive(); err != nil {
		t.Fatal(err)
	}
	if got := <-pong; string(got) != "ak?" {
		t.Fatalf("pong payload %q", got)
	}
}

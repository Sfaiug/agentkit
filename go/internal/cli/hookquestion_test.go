package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAQuestionCardIsRefusedKeptOrLeftToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("AK_RUN_ROLE", "")
	state := filepath.Join(home, ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(name, text string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(state, name), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write("session-acme.json", `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`)
	card := func(extra string) (int, string) {
		var out bytes.Buffer
		code := orchestratorStop([]byte(`{"hook_event_name": "PreToolUse", "tool_input": {"questions": [`+
			`{"question": "Merge it?"}, {"question": "  "}, {"header": "none"}, {"question": "And ship?"}]}`+extra+`}`), &out)
		return code, out.String()
	}
	kept := func() string {
		data, _ := run.ReadJSON(filepath.Join(state, "seat-acme.json"))
		if data == nil || data.Dict("unasked") == nil {
			return ""
		}
		return data.Dict("unasked").Str("text")
	}

	write("plan-acme.md", "- [x] Merge the parser\n")
	if code, out := card(`, "agent_id": "a1"`); code != 0 || out != "" || kept() != "" {
		t.Fatalf("a sub-agent's card: %d %q", code, out)
	}
	t.Setenv("AK_RUN_ROLE", "worker")
	if code, out := card(""); code != 0 || out != "" || kept() != "" {
		t.Fatalf("a worker's card: %d %q", code, out)
	}
	t.Setenv("AK_RUN_ROLE", "")
	code, out := card("")
	if code != 0 || !strings.Contains(out, `"permissionDecision": "deny"`) || !strings.Contains(out, "Your plan is done: every line is proven") || kept() != "" {
		t.Fatalf("a done plan: %d %q", code, out)
	}

	// a run of its own parked undecided lets it ask, and what it asks is kept, after what was
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "runs", "a"), 0o700); err != nil {
		t.Fatal(err)
	}
	record := filepath.Join(home, ".agentkit", "runs", "a", "run.json")
	if err := os.WriteFile(record, []byte(`{"state": "interrupted", "launched_session": "acme", "run_id": "a"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	write("seat-acme.json", `{"word": "working", "wait": {"on": "x"}, "unasked": {"text": "Older?", "at": 3}}`)
	if code, out := card(""); code != 0 || out != "" {
		t.Fatalf("a parked run: %d %q", code, out)
	}
	if got := kept(); got != "Older? Also: Merge it? Also: And ship?" {
		t.Fatalf("kept %q", got)
	}
	data, _ := run.ReadJSON(filepath.Join(state, "seat-acme.json"))
	if data.Get("wait") != nil || data.Str("session") != "acme" || !data.Has("wait") {
		t.Fatalf("its newer word ends its wait: %s", run.Line(data))
	}

	// what Go cannot read prints nothing, keeps nothing and leaves it to Python
	write("seat-acme.json", `{"word": "working"}`)
	project := " · ~/code/acme#0123456789ab"
	written := " · written 2026-10-20 09:00"
	write("plan-acme.md", "- [x] z · check: `true`"+project+written+" · done 0123456789ab init\n- [ ] y · check: `true`"+project+" · deferred"+written+"\n")
	if code, out := card(""); code != 3 || out != "" || kept() != "" {
		t.Fatalf("a deferred line: %d %q", code, out)
	}
	write("plan-acme.md", "- [x] Merge the parser\n")
	write("session-acme.json", `{"orchestrator": "no such model", "cwd": "/code/acme", "conversation": "conv-1"}`)
	if code, out := card(""); code != 3 || out != "" {
		t.Fatalf("a harness Go does not read: %d %q", code, out)
	}
}

func TestAStopReadsTheSameRefusalFromTheSeatsConversation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("AK_RUN_ROLE", "")
	state := filepath.Join(home, ".agentkit", "state")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	stop := func() (int, string) {
		write(filepath.Join(state, "stop-acme.json"), `{"session": "acme", "turn": 5, "blocks": 0}`)
		var out bytes.Buffer
		code := orchestratorStop([]byte(`{"hook_event_name": "Stop", "last_assistant_message": "Merge it?"}`), &out)
		return code, out.String()
	}
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`)
	write(filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	if code, out := stop(); code != 0 || out != "" {
		t.Fatalf("nothing from the owner since: %d %q", code, out)
	}
	// the plan's last write long before the owner's word
	long := time.Unix(1_000_000_000, 0)
	if err := os.Chtimes(filepath.Join(state, "plan-acme.md"), long, long); err != nil {
		t.Fatal(err)
	}
	write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-1.jsonl"),
		`{"type": "user", "timestamp": "2026-10-31T05:00:01Z", "message": {"role": "user", "content": "go on"}}`+"\n")
	if code, out := stop(); code != 0 || !strings.Contains(out, `"decision": "block"`) {
		t.Fatalf("the owner wrote since: %d %q", code, out)
	}
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "no such model", "cwd": "/code/acme", "conversation": "conv-1"}`)
	if code, out := stop(); code != 3 || out != "" {
		t.Fatalf("a harness Go does not read: %d %q", code, out)
	}
}

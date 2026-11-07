package cli

import (
	"bytes"
	"encoding/json"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
)

// This test binary is ak to the hook commands a seat's launch registers, which name the program
// that launched it.
func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == "adapter" {
		os.Exit(Main(os.Args[1:], os.Stdout, os.Stderr))
	}
	// the look a hook here starts after its fact: the test's sandbox may be gone before it ends
	if len(os.Args) > 1 && os.Args[1] == "seat-look" {
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// A Codex seat opened by Go registers a command for each event Codex says what its seat is doing
// with, each run here as Codex runs it: through `sh -c`, the event's JSON on stdin, in the seat's
// environment.  A notice saying what the fact says is not written again, an interrupt always is,
// and a call's end answers only a question standing, with the tool it completed.
func TestACodexSeatsHooksRunAsCodexRunsThem(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Codex runs its hooks under sh")
	}
	home := sandbox(t)
	adapters, err := filepath.Abs(filepath.Join("..", "..", "..", "adapters"))
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	t.Setenv("TMUX", "") // no seat to look at again
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"),
		"[models.astra]\nharness='codex'\nmodel='gpt-6-astra'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "astra"}`)
	// Codex as far as a launch asks it: hook support, then a server that keeps its line and ends
	codex := filepath.Join(home, "codex")
	write(t, codex, "#!/bin/sh\ncase $1 in\n--help) echo '  --dangerously-bypass-hook-trust' ;;\n"+
		"app-server) printf '%s\\0' \"$@\" >\"$HOME/served\" ;;\nesac\n")
	if err := os.Chmod(codex, 0o700); err != nil {
		t.Fatal(err)
	}
	receipt := filepath.Join(state, "codex-launch-"+strings.Repeat("a", 32)+".json")
	write(t, receipt, `{"launch": "`+strings.Repeat("a", 32)+`", "cwd": "`+home+`", "expected": null, "remote": "`+strings.Repeat("b", 32)+`"}`)
	write(t, filepath.Join(home, "rulebook.md"), "Work to the plan.")
	t.Setenv("AGENTKIT_RULEBOOK", filepath.Join(home, "rulebook.md"))
	t.Setenv("AGENTKIT_CODEX_RECEIPT", receipt)
	var said bytes.Buffer
	if code := Main([]string{"adapter", home, "codex", "seat", "--", codex, "--yolo"}, new(bytes.Buffer), &said); code != 1 {
		t.Fatalf("a server that ends: exit %d, %s", code, said.String())
	}
	served, _ := os.ReadFile(filepath.Join(home, "served"))
	words, hooks := strings.Split(string(served), "\x00"), map[string]any{}
	for i, word := range words[:max(len(words)-1, 0)] {
		if word == "-c" && strings.HasPrefix(words[i+1], "hooks.") {
			read, err := config.ReadTOML(words[i+1])
			if err != nil {
				t.Fatalf("%s: %v", words[i+1], err)
			}
			maps.Copy(hooks, read["hooks"].(map[string]any))
		}
	}
	fire := func(event string, fields ...string) hookfact.Fact {
		t.Helper()
		payload := map[string]any{"hook_event_name": event}
		for i := 0; i < len(fields); i += 2 {
			payload[fields[i]] = fields[i+1]
		}
		data, _ := json.Marshal(payload)
		groups, _ := hooks[event].([]any)
		if len(groups) == 0 {
			t.Fatalf("no hook for %s among %v", event, words)
		}
		for _, group := range groups {
			for _, hook := range group.(map[string]any)["hooks"].([]any) {
				run := exec.Command("sh", "-c", hook.(map[string]any)["command"].(string))
				run.Stdin, run.Env = bytes.NewReader(data), append(os.Environ(), "AGENTKIT_SESSION=acme")
				if out, err := run.CombinedOutput(); err != nil {
					t.Fatalf("%s: %v %s", event, err, out)
				}
			}
		}
		return hookfact.Standing("acme")
	}
	answers := func(standing hookfact.Fact, tool string) hookfact.Fact {
		t.Helper()
		after := fire("PostToolUse", "tool_name", tool, "tool_use_id", "call-1")
		if after.Event != "PostToolUse" || after.Kind != tool || after.At <= standing.At {
			t.Fatalf("after %+v a call's end left %+v", standing, after)
		}
		return after
	}
	leaves := func(standing hookfact.Fact) {
		t.Helper()
		if after := fire("PostToolUse", "tool_name", "Bash"); !reflect.DeepEqual(after, standing) {
			t.Fatalf("a call's end after %+v wrote %+v", standing, after)
		}
	}
	fire("SessionStart", "source", "startup")
	stopped := fire("Stop")
	leaves(stopped)
	interrupted := fire("Interrupt", "turn_id", "turn-1")
	if interrupted.Event != "Interrupt" || interrupted.At <= stopped.At {
		t.Fatalf("an interrupt after a Stop: %+v", interrupted)
	}
	again := fire("Interrupt", "turn_id", "turn-2")
	if again.Event != "Interrupt" || again.At <= interrupted.At {
		t.Fatalf("an interrupt after an interrupt: %+v", again)
	}
	leaves(again)
	leaves(fire("UserPromptSubmit", "prompt", "Touch a file outside the workspace."))
	asked := fire("PermissionRequest", "tool_name", "Bash", "tool_use_id", "exec-1")
	if asked.Event != "PermissionRequest" || asked.Kind != "Bash" {
		t.Fatalf("a permission request: %+v", asked)
	}
	if same := fire("PermissionRequest", "tool_name", "Bash", "tool_use_id", "exec-1"); same.At != asked.At {
		t.Fatalf("a second request asking the same wrote %+v", same)
	}
	answers(asked, "Bash")
	planned := fire("PreToolUse", "tool_name", "request_user_input")
	if planned.Event != "PreToolUse" || planned.Kind != "request_user_input" {
		t.Fatalf("a Plan-mode question: %+v", planned)
	}
	answers(planned, "request_user_input")
}

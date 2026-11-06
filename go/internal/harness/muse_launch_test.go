package harness

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/commandhelp"
)

func TestMuseLaunchQuotesThePanesEnvironmentIntoItsHookCommands(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake Muse is a shell script")
	}
	t.Setenv("HOME", t.TempDir())
	program := filepath.Join(t.TempDir(), "muse")
	if err := os.WriteFile(program, []byte("#!/bin/sh\nprintf '%s' '\"notification\"' >\"$4/schema.json\"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	env := []string{"AGENTKIT_SESSION=acme's seat", "TMUX=/tmp/acme's socket,12,1", "TMUX_PANE=%7",
		"AGENTKIT_TMUX_SOCKET=acme socket"}
	words := museSeatWords([]string{program}, env)
	if len(words) != 11 {
		t.Fatalf("hooks missing: %q", words)
	}
	for i := 1; i < len(words); i += 2 {
		event, payload, ok := strings.Cut(words[i+1], "=")
		var groups []struct {
			Hooks []struct {
				Type, Command string
				Async         bool
			}
		}
		if !ok || words[i] != "-c" || json.Unmarshal([]byte(payload), &groups) != nil || len(groups) != 1 || len(groups[0].Hooks) != 1 {
			t.Fatalf("invalid hook settings: %q", words[i:])
		}
		hook := groups[0].Hooks[0]
		command, parsed := commandhelp.ShellSplit(hook.Command)
		if !parsed || command[0] != "env" || !slices.Equal(command[1:1+len(env)], env) || hook.Type != "command" ||
			hook.Async != (event == "hooks.PostToolBatch" || event == "hooks.Interrupt") {
			t.Fatalf("%s lost its environment or execution mode: %+v", event, hook)
		}
	}
	if got := museSeatWords([]string{program}, nil); !slices.Equal(got, []string{program}) {
		t.Fatalf("a launch outside a seat got hooks: %q", got)
	}
}

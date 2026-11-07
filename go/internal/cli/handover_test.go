package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"testing"
)

// The shadow tells where Go handed a case to Python by the line each hand-over leaves in the file
// AK_HANDOVER names, as no exit code can: a command by the file and line that handed it over, a
// tick by the pass that left it, and a hook, which still prints nothing.  An exit 3 that hands
// nothing over leaves none, and with AK_HANDOVER unset nothing is written.
func TestEveryHandOverLeavesItsRecord(t *testing.T) {
	home := sandbox(t)
	t.Setenv("TMUX_TMPDIR", t.TempDir())
	record := filepath.Join(t.TempDir(), "handover")
	t.Setenv("AK_HANDOVER", record)
	call := func(stdin string, args ...string) (code int, printed, left string) {
		t.Helper()
		in := filepath.Join(t.TempDir(), "stdin")
		write(t, in, stdin)
		file, err := os.Open(in)
		if err != nil {
			t.Fatal(err)
		}
		defer file.Close()
		previous := os.Stdin
		os.Stdin = file
		defer func() { os.Stdin = previous }()
		var out, errOut bytes.Buffer
		code = Main(args, &out, &errOut)
		data, _ := os.ReadFile(record)
		os.Remove(record)
		return code, out.String() + errOut.String(), string(data)
	}
	leaves := func(want string, stdin string, args ...string) string {
		t.Helper()
		code, printed, left := call(stdin, args...)
		if code != 3 || !regexp.MustCompile(want).MatchString(left) {
			t.Fatalf("%q: exit %d, leaving %q", args, code, left)
		}
		return printed
	}

	leaves(`^usage: internal/cli/usage\.go:\d+\n$`, "", "usage", "--json")
	pass := "seat health"
	if runtime.GOOS == "windows" {
		pass = "before its passes" // a tick there is Python's whole
	}
	write(t, filepath.Join(home, ".agentkit", "runs", "fix-api", "run.json"), `{"state": "waiting_login"}`)
	leaves("^watch: "+pass+"\n$", "", "watch", "--dry-run")

	// a question card on a seat whose harness Go does not read
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "no such model", "cwd": "/code/acme", "conversation": "conv-1"}`)
	write(t, filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	card := `{"hook_event_name": "PreToolUse", "tool_input": {"questions": [{"question": "Merge it?"}]}}`
	if printed := leaves(`^hook orchestrator-stop: internal/cli/hookquestion\.go:\d+\n$`, card, "hook", "orchestrator-stop"); printed != "" {
		t.Fatalf("the hook printed %q", printed)
	}

	// a TUI that cannot be told a conversation id is the adapter's answer, handing nothing over
	for _, harness := range []string{"codex", "muse"} {
		if code, _, left := call("", "adapter", home, harness, "interactive", "acme-1", "high", "conv-1", "new"); code != 3 || left != "" {
			t.Fatalf("%s: exit %d, leaving %q", harness, code, left)
		}
	}

	t.Setenv("AK_HANDOVER", "")
	os.Unsetenv("AK_HANDOVER")
	if code, _, left := call("", "usage", "--json"); code != 3 || left != "" {
		t.Fatalf("AK_HANDOVER unset: exit %d, leaving %q", code, left)
	}
}

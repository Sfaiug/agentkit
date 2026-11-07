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
// AK_HANDOVER names, as no exit code can: the words of the command that ran, whatever its refusal
// says, and the file and line that handed it over, or for a tick the pass that left it; a hook
// still prints nothing.  An exit 3 that hands nothing over leaves none, and with AK_HANDOVER unset
// nothing is written.
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
	ak := filepath.Join(home, ".agentkit")

	leaves(`^usage: internal/cli/usage\.go:\d+\n$`, "", "usage", "--json")
	pass := "seat health"
	if runtime.GOOS == "windows" {
		pass = "before its passes" // a tick there is Python's whole
	}
	write(t, filepath.Join(ak, "runs", "fix-api", "run.json"), `{"state": "waiting_login"}`)
	leaves("^watch: "+pass+"\n$", "", "watch", "--dry-run")
	// a subcommand main dispatches, and one its command reads, each by its own words
	write(t, filepath.Join(ak, "state", "gc-leftovers.json"), `{"x": "\ud800"}`)
	leaves(`^run gc: internal/cli/rungc\.go:\d+\n$`, "", "run", "gc", "--dry-run")
	leaves(`^run show: internal/cli/run\.go:\d+\n$`, "", "run", "show")

	// a seat whose harness Go does not read: its plan's check, and its question card, which the
	// seat hook Codex is given reads as the stop hook does
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(ak, "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "no such model", "cwd": "/code/acme", "conversation": "conv-1"}`)
	write(t, filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	leaves(`^plan check: internal/cli/plan\.go:\d+\n$`, "", "plan", "check", "٣", "true")
	card := `{"hook_event_name": "PreToolUse", "tool_input": {"questions": [{"question": "Merge it?"}]}}`
	if printed := leaves(`^hook orchestrator-stop: internal/cli/hookquestion\.go:\d+\n$`, card, "hook", "orchestrator-stop"); printed != "" {
		t.Fatalf("the hook printed %q", printed)
	}
	if printed := leaves(`^adapter codex hook: internal/cli/hookquestion\.go:\d+\n$`, card, "adapter", home, "codex", "hook", "orchestrator-stop"); printed != "" {
		t.Fatalf("Codex's hook printed %q", printed)
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

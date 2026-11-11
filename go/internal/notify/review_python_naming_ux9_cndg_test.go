//go:build linux

package notify

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

func TestReviewPythonReceiptNamingKeepsOriginalConversation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "data"))
	t.Setenv("PYTHONDONTWRITEBYTECODE", "1")
	put := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
	}
	const line = "Continue the interrupted turn."
	token := strings.Repeat("a", 32)
	state := filepath.Join(home, ".agentkit", "state")
	receipt := filepath.Join(state, "muse-launch-"+token)
	record := map[string]any{"muse_launch": token}
	put(filepath.Join(state, "input-acme.jsonl"), run.Line(run.Fields(
		"at", 0, "text", line, "source", "ak", "harness", "muse",
		"conversation", nil, "after", 0, "launch", run.Fields("muse_launch", token)))+"\n")
	prompt := func(at int, text string) string {
		return run.Line(run.Fields("recorded_at", at, "payload",
			run.Fields("kind", "run", "run_id", strconv.Itoa(at), "event",
				run.Fields("kind", "started", "prompt", text))))+"\n"
	}
	log := func(session string) string {
		return filepath.Join(home, "data", "muse", "sessions", "2026", "11", "07", session, "session.jsonl")
	}
	put(filepath.Join(receipt, "session"), "acme-first")
	birth, ok := host.ReadIdentity(os.Getpid())
	if !ok {
		t.Fatal("cannot read this process's identity")
	}
	put(filepath.Join(receipt, "lineage"), run.Line(run.Fields("processes", []any{
		[]any{run.Number(strconv.Itoa(os.Getpid())), run.Fields("boot", birth.Boot, "ticks", int(birth.Ticks), "started_at", birth.StartedAt)},
	}, "earlier", []any{})))
	put(log("acme-first"), prompt(1000000, line))
	registry := filepath.Join(home, "data", "muse", "runtime", "muse", "sessions")
	register := func(session string) {
		put(filepath.Join(registry, session+".json"), run.Line(run.Fields(
			"session_id", session, "process_generation_hint", "pid="+strconv.Itoa(os.Getpid()))))
	}
	register("acme-first")
	if conversation, known := harness.Owned("muse", record); !known || conversation != "acme-first" {
		t.Fatalf("initial launch conversation: %q, %v", conversation, known)
	}
	if err := os.Remove(filepath.Join(registry, "acme-first.json")); err != nil {
		t.Fatal(err)
	}
	register("acme-next")
	put(log("acme-next"), prompt(2000000, line)+prompt(3000000, "Add a retry button."))
	// Let Go preserve the original session first. Python's before-relaunch
	// receipt naming must not replace it with the launch's new conversation.
	if conversation, known := harness.Owned("muse", record); !known || conversation != "acme-next" {
		t.Fatalf("Go could not follow the launch: %q, %v", conversation, known)
	}
	python := exec.Command("python3", "-c", "from agentkit import orch; orch.name_receipts('acme')")
	python.Dir = "../../.."
	if output, err := python.CombinedOutput(); err != nil {
		t.Fatalf("Python could not follow the launch: %v\n%s", err, output)
	}
	if current, err := os.ReadFile(filepath.Join(receipt, "session")); err != nil || string(current) != "acme-next" {
		t.Fatalf("Python did not persist the new session: %q, %v", current, err)
	}
	conversation, messages, err := ownerIn("acme", "muse", record, "", false)
	if err != nil || conversation != "acme-next" {
		t.Fatalf("new conversation: %q, %v", conversation, err)
	}
	if len(messages) != 2 || messages[0].Text != line || messages[1].Text != "Add a retry button." {
		t.Fatalf("Python's before-relaunch receipt naming hid a real owner prompt: %+v", messages)
	}
}

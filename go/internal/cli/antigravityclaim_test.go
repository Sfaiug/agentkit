package cli

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// A seat's conversation, learned where its launch's own agy holds one open, is written down by a
// command Go carries through as it ends, and by none that hands the seat to Python first.
func TestAnAntigravityClaimIsWrittenOnlyByACommandGoCarries(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("a process's open files are read off Linux's /proc")
	}
	// a fresh launch, as Go launches one, whose agy holds its conversation's store open
	launch := func(t *testing.T) (path, token string, agy *exec.Cmd) {
		home := sandbox(t)
		write(t, filepath.Join(home, ".agentkit", "config.toml"),
			"[models.gemini]\nharness='antigravity'\nmodel='gemini-3'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
		fields, env := harness.LaunchExtras("antigravity")
		path = filepath.Join(home, ".agentkit", "state", "session-acme.json")
		write(t, path, run.Encode(run.SetAll(fields, "orchestrator", "gemini", "cwd", home))+"\n")
		store := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "c-acme.db")
		write(t, store, "")
		held, err := os.Open(store)
		if err != nil {
			t.Fatal(err)
		}
		defer held.Close()
		agy = exec.Command("sleep", "60")
		agy.Env, agy.ExtraFiles = append(os.Environ(), env...), []*os.File{held}
		if err := agy.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { agy.Process.Kill(); agy.Wait() })
		return path, strings.TrimPrefix(env[0], "AGENTKIT_ANTIGRAVITY_LAUNCH="), agy
	}
	unchanged := func(t *testing.T, path string, before []byte) {
		t.Helper()
		if after, _ := os.ReadFile(path); !bytes.Equal(after, before) {
			t.Fatalf("written: %s", after)
		}
	}

	t.Run("ak orch check, handing it over", func(t *testing.T) {
		path, _, _ := launch(t)
		before, _ := os.ReadFile(path)
		var out, errOut bytes.Buffer
		if code := Main([]string{"orch", "check", "acme"}, &out, &errOut); code != 3 {
			t.Fatalf("exit %d: %s", code, errOut.String())
		}
		unchanged(t, path, before)
	})

	t.Run("a card's retirement pending", func(t *testing.T) {
		path, _, _ := launch(t)
		before, _ := os.ReadFile(path)
		if !notify.AnswersRead("acme") {
			t.Fatal("answers unread with no retirement pending")
		}
		write(t, filepath.Join(filepath.Dir(path), "notification-outbox", "acme.clear"), "{}\n")
		if notify.AnswersRead("acme") {
			t.Fatal("answers read with a retirement pending")
		}
		unchanged(t, path, before)
	})

	t.Run("a command Go carries", func(t *testing.T) {
		path, token, agy := launch(t)
		t.Setenv("AGENTKIT_SESSION", "acme")
		write(t, filepath.Join(filepath.Dir(path), "plan-acme.md"), "- [x] Merge the parser\n")
		// with the done check on, whether a finished plan is done is Python's (plan.checkOwed)
		settings := filepath.Join(filepath.Dir(filepath.Dir(path)), "config.toml")
		kept, _ := os.ReadFile(settings)
		write(t, settings, string(kept)+"[done_check]\non = false\n")
		var out, errOut bytes.Buffer
		// a done plan refuses the question once the owner's words in the conversation are read
		if code := Main([]string{"notify", "needs", "Merge it?"}, &out, &errOut); code != 2 || !strings.Contains(errOut.String(), "Your plan is done") {
			t.Fatalf("exit %d: %s", code, errOut.String())
		}
		if kept, _ := run.ReadJSON(path); !run.Equal(kept.Get("antigravity_open"), run.Fields("launch", token, "conversation", "c-acme")) {
			t.Fatalf("written down: %s", run.Encode(kept))
		}
		agy.Process.Kill()
		agy.Wait()
		_, record, err := config.ResolveSession("acme")
		if conversation, known := harness.Owned("antigravity", record); err != nil || conversation != "c-acme" || !known {
			t.Fatalf("once agy exits: %q %v %v", conversation, known, err)
		}
	})
}

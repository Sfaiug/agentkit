package cli

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A seat whose current conversation is named by a live Antigravity launch, or by its hook, is
// handed to Python by `ak orch check` before any reader takes the claim's lock or writes into HOME.
func TestOrchCheckHandsALiveAntigravitySeatOverBeforeLearningItsClaim(t *testing.T) {
	t.Run("a launch whose agy holds one store open", func(t *testing.T) {
		if runtime.GOOS != "linux" {
			t.Skip("a process's open files are read off Linux's /proc")
		}
		home := sandbox(t)
		t.Setenv("AGENTKIT_ADAPTER_DIR", "")
		write(t, filepath.Join(home, ".agentkit", "config.toml"),
			"[models.mid]\nharness='antigravity'\nmodel='acme/m'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
		fields, env := harness.LaunchExtras("antigravity")
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(state, "session-acme.json"), run.Encode(run.SetAll(fields, "orchestrator", "mid", "cwd", home))+"\n")
		store := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "c-acme.db")
		write(t, store, "")
		file, err := os.Open(store)
		if err != nil {
			t.Fatal(err)
		}
		defer file.Close()
		agy := exec.Command("cat")
		agy.Env, agy.ExtraFiles = append(os.Environ(), env...), []*os.File{file}
		in, err := agy.StdinPipe()
		if err != nil {
			t.Fatal(err)
		}
		out, err := agy.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err := agy.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { agy.Process.Kill(); agy.Wait() })
		if _, err := in.Write([]byte("\n")); err != nil {
			t.Fatal(err)
		}
		if _, err := io.ReadFull(out, make([]byte, 1)); err != nil {
			t.Fatal(err)
		}
		before := tree(t, home)
		var stdout, stderr bytes.Buffer
		if code := Main([]string{"orch", "check", "acme"}, &stdout, &stderr); code != 3 || stdout.Len() != 0 {
			t.Fatalf("got (%d, %q, %q), want exit 3", code, stdout.String(), stderr.String())
		}
		if after := tree(t, home); !reflect.DeepEqual(before, after) {
			t.Fatalf("orch check wrote before handing over: %v", after)
		}
	})

	t.Run("a conversation its hook followed after leaving another", func(t *testing.T) {
		home := sandbox(t)
		t.Setenv("AGENTKIT_ADAPTER_DIR", "")
		write(t, filepath.Join(home, ".agentkit", "config.toml"),
			"[models.mid]\nharness='antigravity'\nmodel='acme/m'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "mid", "cwd": "/code/acme", `+
			`"id_source": "antigravity-hook", "conversation": "c-after", `+
			`"left": [{"harness": "claude", "conversation": "c-before"}]}`+"\n")
		before := tree(t, home)
		var stdout, stderr bytes.Buffer
		if code := Main([]string{"orch", "check", "acme"}, &stdout, &stderr); code != 3 || stdout.Len() != 0 {
			t.Fatalf("got (%d, %q, %q), want exit 3", code, stdout.String(), stderr.String())
		}
		if after := tree(t, home); !reflect.DeepEqual(before, after) {
			t.Fatalf("orch check wrote before handing over: %v", after)
		}
	})
}

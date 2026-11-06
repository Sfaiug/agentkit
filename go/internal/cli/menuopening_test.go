package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/host"
)

func TestTheMenuSweepsOnlyAHomeItAdmitsAndDrawsWhatTheSweepLeft(t *testing.T) {
	if host.BootID() == "" {
		t.Skip("no boot id to tell another boot by")
	}
	in, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	previous := os.Stdin
	os.Stdin = in
	defer func() { os.Stdin = previous }()
	bin := t.TempDir()
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\necho 'no server running on /tmp/none' >&2\nexit 1\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	t.Setenv("COLUMNS", "80")
	for _, boot := range []string{"another", "this"} {
		t.Run(boot, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			state := filepath.Join(home, ".agentkit", "state")
			write(t, filepath.Join(home, ".agentkit", "config.toml"),
				"[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
			record, _ := json.Marshal(map[string]any{"orchestrator": "opus", "workers": []string{"opus"}, "cwd": home,
				"created": time.Now().Unix() - 10*86400, "seen": time.Now().Unix() - 8*86400, "conversation": "conv-acme",
				"id_source": "launcher", "resumable": true, "repo": nil})
			write(t, filepath.Join(state, "session-acme.json"), string(record))
			if boot == "another" { // its resume is Python's, from the record as the boot left it
				write(t, filepath.Join(state, "watch.json"), `{"boot_id": "prior-boot"}`)
			}
			var out, errOut bytes.Buffer
			code := Main(nil, &out, &errOut)
			_, kept := os.Lstat(filepath.Join(state, "session-acme.json"))
			if boot == "another" && (code != 3 || kept != nil) {
				t.Fatalf("exit=%d record: %v", code, kept)
			}
			if boot == "this" && (code != 0 || kept == nil || !strings.HasPrefix(out.String(), " forgot the session acme, gone for 8d\nagentkit") ||
				!strings.Contains(out.String(), "no sessions; n starts one")) {
				t.Fatalf("exit=%d record: %v stdout=%q stderr=%q", code, kept, out.String(), errOut.String())
			}
		})
	}
}

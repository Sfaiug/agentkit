package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The screen of a home with a seat, which its reading admits only with what the menu keeps.
func TestALineAJobLeftIsShownOnceAfterTheUpdatesResult(t *testing.T) {
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
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write(t, filepath.Join(home, ".agentkit", "config.toml"),
		"[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	state := filepath.Join(home, ".agentkit", "state")
	record, _ := json.Marshal(map[string]any{"orchestrator": "opus", "workers": []string{"opus"}, "cwd": home,
		"created": time.Now().Unix() - 900, "seen": time.Now().Unix(), "conversation": "conv-acme",
		"id_source": "launcher", "resumable": true, "repo": nil})
	write(t, filepath.Join(state, "session-acme.json"), string(record))
	result, notices := filepath.Join(state, "update-result"), filepath.Join(state, "notices")
	screen := func(notice string) {
		t.Helper()
		var out, errOut bytes.Buffer
		if code := Main(nil, &out, &errOut); code != 0 || !strings.HasPrefix(out.String(), notice+"agentkit") {
			t.Fatalf("exit=%d stdout=%.2000q stderr=%q, want it to start %q", code, out.String(), errOut.String(), notice)
		}
	}
	write(t, result, "update: done (acme)\n")
	write(t, notices, "stop: fix-api is still running\n")
	screen(" update: done (acme)\n stop: fix-api is still running\n")
	if _, err := os.Stat(result); !os.IsNotExist(err) {
		t.Fatalf("update-result is still there (%v)", err)
	}
	if data, err := os.ReadFile(notices); err != nil || len(data) != 0 {
		t.Fatalf("notices holds %q (%v), want it there and empty", data, err)
	}
	screen("")
	os.Remove(notices)
	screen("")
	for _, path := range []string{result, notices} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("%s was made (%v)", filepath.Base(path), err)
		}
	}
}

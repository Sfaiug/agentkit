package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

// With no adapter to ask, Go reads the login a turn would run on: the usual one, whatever account
// this process was handed, as ChildEnv leaves the scripted probe.
func TestUnreadyReadsTheUsualLoginWithNoAdapterToAsk(t *testing.T) {
	home, bin := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", bin)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "")
	t.Setenv("AGENTKIT_ACCOUNT", "first")
	if err := os.WriteFile(filepath.Join(bin, "claude"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	model := config.Model{Harness: "claude", Provider: "acme"}
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700); err != nil {
		t.Fatal(err)
	}
	toml := "[models.beta]\nharness='claude'\nmodel='beta'\neffort='high'\nprovider='acme'\n[providers.acme]\nmode='subscription'\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(toml), 0o600); err != nil {
		t.Fatal(err)
	}
	if why := unready(model); why != "claude is not logged in" {
		t.Fatalf("no login at all: %q", why)
	}
	secrets := filepath.Join(home, ".agentkit", "secrets")
	if err := os.MkdirAll(secrets, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(secrets, "claude_oauth_token"), []byte("token"), 0o600); err != nil {
		t.Fatal(err)
	}
	if why := unready(model); why != "" {
		t.Fatalf("a usual login under an inherited account: %q", why)
	}
}

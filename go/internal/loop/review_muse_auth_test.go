package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

func TestReviewMuseWorkerUsesUsualLoginInsideANamedAccountSeat(t *testing.T) {
	home, bin := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", bin)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("AGENTKIT_ACCOUNT", "second")
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".muse-second"))
	t.Setenv("META_API_KEY", "")
	t.Setenv("AGENTKIT_MUSE_PROVIDER", "")
	if err := os.WriteFile(filepath.Join(bin, "muse"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{filepath.Join(home, ".agentkit"), filepath.Join(home, ".config", "muse")} {
		if err := os.MkdirAll(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	toml := "[models.spark]\nharness='muse'\nmodel='muse-spark-1.3'\neffort='minimal'\nprovider='meta'\n[providers.meta]\nmode='subscription'\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(toml), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".config", "muse", "auth.json"), []byte(`{"token":"acme"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if why := unready(config.Model{Harness: "muse", Provider: "meta"}); why != "" {
		t.Fatalf("authenticated usual worker login was rejected under the parent's named account: %s", why)
	}
}

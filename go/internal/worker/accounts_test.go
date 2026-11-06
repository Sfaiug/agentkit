package worker

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestATurnOnAProviderListingAccountsIsPythons(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", t.TempDir())
	listed := "[models.glint]\nharness='acme'\nmodel='acme-1'\neffort='high'\nprovider='acme'\n" +
		"[providers.acme]\nmode='subscription'\naccounts=['shoal','reef']\n"
	if os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700) != nil || os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600) != nil {
		t.Fatal("no config")
	}
	if _, _, err := Turn("glint", "executor", "do it", home, t.TempDir(), "", Given{}, io.Discard); !errors.Is(err, ErrPython) {
		t.Fatalf("a turn went out with no account picked: %v", err)
	}
}

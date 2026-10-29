package config

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
)

func TestSeatEnvReadsAdaptersUnderAHomeNamedLikeAPattern(t *testing.T) {
	home := filepath.Join(t.TempDir(), "a[b]")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "~/adapters")
	dir := filepath.Join(home, "adapters")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(dir, "acme.toml"), []byte("[launch]\nseat_env = [\"ACME_SEAT\"]\n"), 0o600)
	if names, err := SeatEnv(); err != nil || !slices.Contains(names, "ACME_SEAT") {
		t.Fatalf("got %v %v", names, err)
	}
}

func TestRepoEnvReadsTheProjectsEnvFile(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	if env, err := RepoEnv("/code/acme"); env != nil || err != nil {
		t.Fatalf("no file: %v %v", env, err)
	}
	path := filepath.Join(home, ".agentkit", "env", "acme.env")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(path, []byte("# secrets\r\nexport  TOKEN = \"a b\"\n\nPLAIN=x=y\nQUOTE='\n"), 0o600)
	env, err := RepoEnv("/code/acme")
	if want := map[string]string{"TOKEN": "a b", "PLAIN": "x=y", "QUOTE": "'"}; err != nil || !reflect.DeepEqual(env, want) {
		t.Fatalf("got %v %v", env, err)
	}
	os.WriteFile(path, []byte("A=1\nsecret value\n"), 0o600)
	if _, err := RepoEnv("/code/acme"); err == nil || !strings.HasSuffix(err.Error(), "acme.env:2: not a KEY=value line") {
		t.Fatalf("got %v", err)
	}
}

func TestEmbeddedAdapters(t *testing.T) {
	source, _ := filepath.Glob("../../../adapters/*.toml")
	shipped, _ := filepath.Glob("adapters/*.toml")
	if len(source) != len(shipped) {
		t.Fatal("embedded adapter manifests differ from adapters/; run go generate ./internal/config")
	}
	for _, path := range source {
		want, _ := os.ReadFile(path)
		if got, _ := os.ReadFile(filepath.Join("adapters", filepath.Base(path))); string(got) != string(want) {
			t.Fatalf("%s differs from adapters/; run go generate ./internal/config", path)
		}
	}
	names, err := SeatEnv()
	if err != nil || len(names) == 0 {
		t.Fatalf("seat variables %v %v", names, err)
	}
}

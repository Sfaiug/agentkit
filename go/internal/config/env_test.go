package config

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

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

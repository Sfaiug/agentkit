package config

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func modelsHome(t *testing.T, text string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	whole := text + "[models.acme]\nharness = 'echo'\nmodel = 'echo-1'\neffort = 'low'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(whole), 0o666); err != nil {
		t.Fatal(err)
	}
}

func TestLegacyWithinIsIgnored(t *testing.T) {
	for _, text := range []string{"within = 1\n", "within = 'near'\n", "within = -1\n", "within = true\n", "within = 101\n"} {
		modelsHome(t, text)
		if _, err := Compare(); err != nil {
			t.Fatalf("%q: %v", text, err)
		}
	}
}

func TestCompareIsTheConfigsMarks(t *testing.T) {
	modelsHome(t, "")
	if got, err := Compare(); err != nil || got != nil {
		t.Fatalf("none: %v %v", got, err)
	}
	modelsHome(t, "compare = ['acme-5', 'bolt-3']\n")
	if got, err := Compare(); err != nil || !reflect.DeepEqual(got, []string{"acme-5", "bolt-3"}) {
		t.Fatalf("marks: %v %v", got, err)
	}
}

func TestAMarkOfTheWrongKindIsRefused(t *testing.T) {
	for _, text := range []string{"compare = [1]\n", "compare = 'acme-5'\n"} {
		modelsHome(t, text)
		if _, err := Compare(); err == nil {
			t.Errorf("%q was not refused", text)
		}
	}
}

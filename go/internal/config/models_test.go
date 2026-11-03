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

func TestWithinIsTheConfigsElseTheDefault(t *testing.T) {
	modelsHome(t, "")
	if got, err := Within(); err != nil || got != 5 {
		t.Fatalf("default: %v %v", got, err)
	}
	for text, want := range map[string]float64{"within = 2.5\n": 2.5, "within = 0\n": 0, "within = 10\n": 10} {
		modelsHome(t, text)
		if got, err := Within(); err != nil || got != want {
			t.Fatalf("%q: %v %v", text, got, err)
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

func TestAMarkOrWithinOfTheWrongKindIsRefused(t *testing.T) {
	for _, text := range []string{"compare = [1]\n", "compare = 'acme-5'\n", "within = 'near'\n", "within = -1\n", "within = 101\n"} {
		modelsHome(t, text)
		if _, err := Within(); err == nil {
			t.Errorf("%q was not refused", text)
		}
	}
}

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
		if _, _, err := ModelList(); err != nil {
			t.Fatalf("%q: %v", text, err)
		}
	}
}

func TestTheModelListIsTheConfigs(t *testing.T) {
	modelsHome(t, "")
	if companies, off, err := ModelList(); err != nil || companies != nil || off != nil {
		t.Fatalf("none: %v %v %v", companies, off, err)
	}
	modelsHome(t, "companies = []\nmodels_off = ['acme-5', 'bolt-3']\n")
	if companies, off, err := ModelList(); err != nil || companies == nil || len(companies) != 0 ||
		!reflect.DeepEqual(off, []string{"acme-5", "bolt-3"}) {
		t.Fatalf("set: %v %v %v", companies, off, err)
	}
	for _, text := range []string{"models_off = [1]\n", "companies = 'Acme'\n"} {
		modelsHome(t, text)
		if _, _, err := ModelList(); err == nil {
			t.Errorf("%q was not refused", text)
		}
	}
}

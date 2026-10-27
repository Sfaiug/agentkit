package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEmbeddedDefault(t *testing.T) {
	data, err := os.ReadFile("../../../config.default.toml")
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != defaultConfig {
		t.Fatal("embedded defaults differ from config.default.toml; run go generate ./internal/config")
	}
	root, err := parseDocument(defaultConfig)
	if err != nil {
		t.Fatal(err)
	}
	if err := validate(root); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaRefusals(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(Home(), 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(Home(), "config.toml")
	const models = "[models.acme]\nharness='echo'\nmodel='echo-1'\neffort='low'\nprovider='test'\n[providers.test]\n"
	for _, example := range []struct{ config, reason string }{
		{"[defaults]\n", "missing [models] table"},
		{"[models]\n", "missing [providers] table"},
		{"[models]\n[providers]\n", "no [models.*] entry names a provider with a [providers.*] table"},
		{"defaults=1\n" + models, "[defaults] must be a table"},
		{"within=-1\n" + models, "within must be a number of points, 0 or more (got -1)"},
		{"within=true\n" + models, "within must be a number of points, 0 or more (got True)"},
		{"compare='acme-pro-5'\n" + models, "compare must list release slugs (compare = [\"acme-pro-5\"]) (got 'acme-pro-5')"},
		{"compare=['acme-pro-5',1]\n" + models, "compare must list release slugs (compare = [\"acme-pro-5\"]) (got ['acme-pro-5', 1])"},
		{"[defaults]\norchestrator=1\n" + models, "[defaults].orchestrator must be a model name (got 1)"},
		{"[defaults]\nworkers='acme'\n" + models, "[defaults].workers must list distinct model names (got 'acme')"},
		{"[defaults]\nworkers=['acme','acme']\n" + models, "[defaults].workers must list distinct model names (got ['acme', 'acme'])"},
		{"[defaults]\nreviewers=[]\n" + models, "[defaults].reviewers must list distinct model names (got [])"},
		{models + "accounts=['../outside']\n", "[providers.test].accounts must list distinct names of letters, digits, '.', '_' and '-' (got ['../outside'])"},
	} {
		if err := os.WriteFile(path, []byte(example.config), 0600); err != nil {
			t.Fatal(err)
		}
		err := Check()
		if err == nil || err.Error() != path+": "+example.reason {
			t.Errorf("%q: got %v, want %s", example.config, err, example.reason)
		}
	}
	for _, data := range []string{"", "max_runs=1\n", models, "[defaults]\nworkers=[]\n" + models, "[defaults]\nworkers=[\"ac\\u006de\"]\n" + models} {
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if err := Check(); err != nil {
			t.Errorf("valid config %q: %v", data, err)
		}
	}
	if err := CheckModel("absent"); err == nil || !strings.Contains(err.Error(), "defines: acme") {
		t.Fatalf("unknown model: %v", err)
	}
	if err := CheckModel("acme"); err != nil {
		t.Fatal(err)
	}
}

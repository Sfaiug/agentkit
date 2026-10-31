package config

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// Every place ak keeps is owner-only after EnsureDirs, one made before by someone else too,
// and a file where a place goes is refused and left as it was, with what EnsureDirs made and
// changed on the way taken back.
func TestEnsureDirs(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(Home(), "state")
	if err := os.MkdirAll(state, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(state, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := EnsureDirs(); err != nil {
		t.Fatal(err)
	}
	for _, place := range []string{"", "runs", "wt", "state", "secrets", "tmp", "env", "work", "jobs"} {
		info, err := os.Stat(filepath.Join(Home(), place))
		if err != nil || !info.IsDir() || runtime.GOOS != "windows" && info.Mode().Perm() != 0o700 {
			t.Fatalf("%q after EnsureDirs: %v %v", place, info, err)
		}
	}
	jobs := filepath.Join(Home(), "jobs")
	if err := os.Remove(jobs); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(jobs, []byte("acme"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(jobs)
	if err != nil {
		t.Fatal(err)
	}
	wt := filepath.Join(Home(), "wt")
	if err := os.Remove(wt); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(state, 0o755|os.ModeSticky); err != nil {
		t.Fatal(err)
	}
	shared, err := os.Stat(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := EnsureDirs(); err == nil {
		t.Fatal("EnsureDirs took a file named jobs for its folder")
	}
	if after, err := os.Stat(jobs); err != nil || after.Mode() != before.Mode() {
		t.Fatalf("the file named jobs was changed: %v %v", after, err)
	}
	if _, err := os.Stat(wt); !os.IsNotExist(err) {
		t.Fatalf("a failed EnsureDirs left wt made: %v", err)
	}
	if info, err := os.Stat(state); err != nil || info.Mode() != shared.Mode() {
		t.Fatalf("a failed EnsureDirs left state changed: %v %v", info, err)
	}
}

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
		{"within=-1\n" + models, "within must be a number of points from 0 to 10 (got -1)"},
		{"within=11\n" + models, "within must be a number of points from 0 to 10 (got 11)"},
		{"within=true\n" + models, "within must be a number of points from 0 to 10 (got True)"},
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
	if _, err := ModelNamed("absent"); err == nil || !strings.Contains(err.Error(), "defines: acme") {
		t.Fatalf("unknown model: %v", err)
	}
	if _, err := ModelNamed("acme"); err != nil {
		t.Fatal(err)
	}
}

// Resolve follows links name by name as Python's Path.resolve() does: a `..` leaves the link's
// target, and a link that loops is kept.
func TestResolveFollowsLinksBeforeTheirParents(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Python takes each .. away first on Windows")
	}
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for _, step := range [][2]string{{"real/inner", ""}, {"real/inner", "link"}, {"/", "root"}, {"loop", "loop"}} {
		if step[1] == "" {
			err = os.MkdirAll(filepath.Join(dir, step[0]), 0o700)
		} else {
			err = os.Symlink(step[0], filepath.Join(dir, step[1]))
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(dir + "/link"); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(cwd)
	for path, want := range map[string]string{
		dir + "/link/../api.py":     dir + "/real/api.py",
		dir + "//./link/missing/..": dir + "/real/inner",
		dir + "/root/..":            "/",
		dir + "/loop/x":             dir + "/loop/x",
		"../../~/x":                 dir + "/~/x",
		"":                          dir + "/real/inner",
	} {
		if got := Resolve(path); got != want {
			t.Errorf("Resolve(%q) = %q, want %q", path, got, want)
		}
	}
	// Absolute puts the home in `~`'s place and leaves the rest to Resolve as spelled
	t.Setenv("HOME", dir+"/")
	if got := Absolute("~/link/../api.py"); got != dir+"/real/api.py" {
		t.Errorf("Absolute(~/link/../api.py) = %q", got)
	}
}

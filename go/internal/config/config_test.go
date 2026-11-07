package config

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
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

// Callers making a fresh home at once each succeed, the folders above it included: one made by
// another caller between a look and a Mkdir is still a folder.
func TestEnsureDirsAtOnce(t *testing.T) {
	for range 20 {
		home := filepath.Join(t.TempDir(), "acme", "home")
		t.Setenv("HOME", home)
		t.Setenv("USERPROFILE", home)
		errs := make(chan error, 16)
		var done sync.WaitGroup
		for range cap(errs) {
			done.Add(1)
			go func() { defer done.Done(); errs <- EnsureDirs() }()
		}
		done.Wait()
		close(errs)
		for err := range errs {
			if err != nil {
				t.Fatal(err)
			}
		}
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
		{"review_rounds=-1\n" + models, "review_rounds must be a whole number of at least 0, the review rounds a change has before it goes back to its orchestrator to split or re-scope (got -1)"},
		{"review_rounds='no limit'\n" + models, "review_rounds must be a whole number of at least 0, the review rounds a change has before it goes back to its orchestrator to split or re-scope (got 'no limit')"},
		{"executor_lines='many'\n" + models, "executor_lines must be a whole number of at least 0 or \"no limit\", the most added lines a first review reads (got 'many')"},
		{"executor_lines=-1\n" + models, "executor_lines must be a whole number of at least 0, the most added lines a first review reads (got -1)"},
		{"executor_lines=0\norchestrator_lines=0\n" + models, "executor_lines and orchestrator_lines cannot both be 0: nobody could build a change"},
		{"orchestrator_lines=true\n" + models, "orchestrator_lines must be a whole number of at least 0, the most added lines an orchestrator builds (got True)"},
		{"rounds=2\n" + models, "use review_rounds instead of rounds"},
		{"review_lines=9\nexecutor_lines=9\n" + models, "use executor_lines instead of review_lines"},
		{"seat_lines=0\n" + models, "use orchestrator_lines instead of seat_lines"},
		{"review_rounds=2.5\n", "review_rounds must be a whole number of at least 0, the review rounds a change has before it goes back to its orchestrator to split or re-scope (got 2.5)"},
		{"models_off=5\n", "models_off must list release slugs (models_off = [\"acme-pro-5\"]) (got 5)"},
		{"[models.acme]\nprovider='test'\n[providers.test]\n", "no [models.*] entry names a provider with a [providers.*] table"},
		{"[defaults]\n", "missing [models] table"},
		{"[models]\n", "missing [providers] table"},
		{"[models]\n[providers]\n", "no [models.*] entry names a provider with a [providers.*] table"},
		{"defaults=1\n" + models, "[defaults] must be a table"},
		{"models_off='acme-pro-5'\n" + models, "models_off must list release slugs (models_off = [\"acme-pro-5\"]) (got 'acme-pro-5')"},
		{"companies=['Acme',1]\n" + models, "companies must list makers as the boards name them (companies = [\"Acme\", \"Bolt\"]) (got ['Acme', 1])"},
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
	for _, data := range []string{"", "max_runs=1\n", models, "review_rounds=0\n", "executor_lines=0\n", "executor_lines=10\norchestrator_lines=20\n" + models,
		"executor_lines='no limit'\norchestrator_lines='no limit'\n" + models, "[defaults]\nworkers=[]\n" + models, "[defaults]\nworkers=[\"ac\\u006de\"]\n" + models} {
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

// Pure spells a path as PurePosixPath does: empty and `.` names go, `..` stays, and only a
// leading `//` of exactly two is kept.
func TestPureKeepsWhatPathlibKeeps(t *testing.T) {
	for path, want := range map[string]string{"/a/./b/../c//": "/a/b/../c", "//a/b": "//a/b", "///a": "/a", "./": "."} {
		if got := Pure(path); got != want {
			t.Errorf("Pure(%q) = %q, want %q", path, got, want)
		}
	}
}

// Resolve follows links name by name as Python's Path.resolve() does: a `..` leaves the link's
// target, and a link that loops is kept.
func TestRoundsReadsWhatLoadLeaves(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(Home(), 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(Home(), "config.toml")
	const models = "[models.acme]\nharness='echo'\nmodel='echo-1'\neffort='low'\nprovider='test'\n[providers.test]\n"
	for _, example := range []struct {
		config string
		want   int
		reason string
	}{
		{config: models, want: defaultRounds},
		{config: "review_rounds=5\n" + models, want: 5},
		{config: "review_rounds=5\n", want: 5},
		{config: "review_rounds=0\n" + models, want: 0},
		{config: "review_rounds=99999999999999999999\n" + models, reason: "(got 99999999999999999999)"},
	} {
		if err := os.WriteFile(path, []byte(example.config), 0600); err != nil {
			t.Fatal(err)
		}
		numbers, err := HostNumbers()
		got := numbers.Rounds
		if example.reason == "" && (err != nil || got != example.want) {
			t.Errorf("%q: got %d, %v, want %d", example.config, got, err, example.want)
		}
		if example.reason != "" && (err == nil || !strings.HasPrefix(err.Error(), path+": review_rounds must be a whole number of at least 0, ") || !strings.HasSuffix(err.Error(), example.reason)) {
			t.Errorf("%q: got %v, want a refusal ending %s", example.config, err, example.reason)
		}
	}
}

// A HOME of a link and `..` names the link target's parent, as for Python, in a path joined under Home.
func TestHomeFollowsLinksBeforeTheirParents(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Python takes each .. away first on Windows")
	}
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dir+"/real/inner", 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real/inner", dir+"/link"); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", dir+"/link/..")
	if got, want := filepath.Join(Home(), "state"), dir+"/real/.agentkit/state"; got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

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

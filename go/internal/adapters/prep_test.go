package adapters

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	record "agentkit/internal/run"
)

const preparing = `[account]
env = "ACME_HOME"
usual = "~/.acme"
home = "~/.acme-{account}"

[prep]
file = "~/.acme.json"
account = "{home}/.acme.json"
reads = ["~/.acme/settings.json"]
links = ["skills", "gone", "kept"]

[prep.answers]
seen = true
projects."{folder}".trusted = true

[prep.defaults]
theme = "dark"
`

// prepHome is a throwaway HOME, acme's manifest holding text, and a seat's folder to run in.
func prepHome(t *testing.T, text string) (home, folder string) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	adapters := t.TempDir()
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_ADAPTER_DIR": adapters,
		"AGENTKIT_ACCOUNT": "", "ACME_HOME": ""} {
		t.Setenv(key, value)
	}
	folder = filepath.Join(home, "code", "acme")
	if err := os.MkdirAll(folder, 0o777); err != nil {
		t.Fatal(err)
	}
	chdir(t, folder)
	return home, folder
}

// chdir runs the rest of the test in dir, $PWD naming it as a shell's would, which Getwd believes.
func chdir(t *testing.T, dir string) {
	t.Helper()
	before, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(before) })
	t.Setenv("PWD", dir)
}

func put(t *testing.T, path, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
}

func text(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func holds(t *testing.T, path string) *record.Object {
	t.Helper()
	data, err := record.ReadJSON(path)
	if data == nil {
		t.Fatalf("%s: %v", path, err)
	}
	return data
}

// What the owner had stays as json.dumps would write it back: its order, a number too long for
// a float, a null where a default would go.
func TestPrepKeepsWhatTheFileHeld(t *testing.T) {
	home, folder := prepHome(t, preparing)
	file := filepath.Join(home, ".acme.json")
	put(t, file, `{"zeta": 12345678901234567890, "alpha": "<é>", "theme": null, "projects": {"/srv/beta": {"x": 1.5}}}`)
	if err := prepare("acme", config.Login{}); err != nil {
		t.Fatal(err)
	}
	want := `{"zeta": 12345678901234567890, "alpha": "<\u00e9>", "theme": null, "projects": {"/srv/beta": {"x": 1.5}, ` +
		record.Line(folder) + `: {"trusted": true}}, "seen": true}` + "\n"
	if got := text(t, file); got != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
}

// The harness trusts the folder itself, however the seat's $PWD spells it.
func TestPrepTrustsTheFolderALinkLeadsTo(t *testing.T) {
	home, folder := prepHome(t, preparing)
	link := filepath.Join(home, "link")
	if err := os.Symlink(folder, link); err != nil {
		t.Skip(err)
	}
	chdir(t, link)
	if err := prepare("acme", config.Login{}); err != nil {
		t.Fatal(err)
	}
	projects := holds(t, filepath.Join(home, ".acme.json")).Dict("projects")
	if keys := projects.Keys(); len(keys) != 1 || keys[0] != folder {
		t.Fatalf("trusted %q, want %q", keys, folder)
	}
}

// What cannot be answered in without losing something, or read at all, stops the line and the
// seat, and the file stays as it is with nothing left beside it.
func TestPrepRefusesAndLeavesTheFileAlone(t *testing.T) {
	home, folder := prepHome(t, preparing)
	file := filepath.Join(home, ".acme.json")
	for _, held := range []string{"", "{bad", "[]", "null", "{} {}", "{\"a\": \"\xff\"}", `{"projects": []}`,
		`{"projects": null}`, `{"projects": {` + record.Line(folder) + `: []}}`} {
		put(t, file, held)
		_, _, checked := answered("acme")
		err := prepare("acme", config.Login{})
		if checked == nil || err == nil || !strings.Contains(err.Error(), file) {
			t.Errorf("%q: line %v, seat %v", held, checked, err)
		}
		if got := text(t, file); got != held {
			t.Errorf("%q became %q", held, got)
		}
		if found, _ := filepath.Glob(file + ".*"); len(found) != 0 {
			t.Errorf("%q left %q", held, found)
		}
	}
}

// A named login's answers are in its own file, with the usual file's `true`s and links from its
// home; the usual file is only read, and one unreadable sends nothing over.
func TestPrepOnANamedLogin(t *testing.T) {
	home, folder := prepHome(t, preparing)
	t.Setenv("AGENTKIT_ACCOUNT", "work")
	usual, own := filepath.Join(home, ".acme.json"), filepath.Join(home, ".acme-work", ".acme.json")
	login := config.Login{Account: "work", Usual: filepath.Join(home, ".acme"), Home: filepath.Join(home, ".acme-work")}
	shared := `{"notice": true, "off": false, "id": "usual", "projects": {"/srv/beta": {}}}`
	put(t, usual, shared)
	put(t, filepath.Join(login.Usual, "skills", "one"), "")
	put(t, filepath.Join(login.Usual, "kept"), "usual")
	put(t, filepath.Join(login.Home, "kept"), "own")
	if err := prepare("acme", login); err != nil {
		t.Fatal(err)
	}
	data := holds(t, own)
	for key, want := range map[string]any{"notice": true, "seen": true, "theme": "dark", "off": nil, "id": nil} {
		if data.Get(key) != want {
			t.Errorf("%s: %v", key, data.Get(key))
		}
	}
	if keys := data.Dict("projects").Keys(); len(keys) != 1 || keys[0] != folder {
		t.Errorf("trusted %q", keys)
	}
	if text(t, usual) != shared {
		t.Errorf("the usual file became %s", text(t, usual))
	}
	if _, err := os.Stat(filepath.Join(login.Home, "skills", "one")); err != nil {
		t.Error(err)
	}
	if _, err := os.Lstat(filepath.Join(login.Home, "gone")); err == nil {
		t.Error("linked what the usual home lacks")
	}
	if got := text(t, filepath.Join(login.Home, "kept")); got != "own" {
		t.Errorf("kept became %s", got)
	}

	put(t, usual, "{bad")
	put(t, own, `{"id": "work"}`)
	if err := prepare("acme", login); err != nil {
		t.Fatal(err)
	}
	if data := holds(t, own); data.Str("id") != "work" || data.Has("notice") || data.Get("seen") != true {
		t.Errorf("after an unreadable usual file: %s", record.Line(data))
	}
	put(t, own, "{bad")
	if _, _, err := answered("acme"); err == nil || !strings.Contains(err.Error(), own) {
		t.Errorf("its own file unreadable: %v", err)
	}
}

// A harness with no `[prep]` starts without one, and a manifest's answer JSON would not hold as
// written is its author's to fix.
func TestPrepOnlyWhereTheManifestSays(t *testing.T) {
	home, _ := prepHome(t, "[launch]\nseat = [\"acme\"]\n")
	if err := prepare("acme", config.Login{}); err != nil {
		t.Fatal(err)
	}
	if found, _ := filepath.Glob(filepath.Join(home, ".*")); len(found) != 0 {
		t.Errorf("wrote %q", found)
	}
	prepHome(t, preparing+"count = 3\n")
	if err := prepare("acme", config.Login{}); err == nil || !strings.Contains(err.Error(), "acme.toml") {
		t.Errorf("a number as an answer: %v", err)
	}
}

// A write that cannot end leaves what was there, and no temp file.
func TestReplaceIsWholeOrNotAtAll(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "held")
	put(t, filepath.Join(path, "inside"), "kept")
	if err := replace(path, "{}"); err == nil {
		t.Fatal("replaced a directory")
	}
	if found, _ := os.ReadDir(dir); len(found) != 1 || text(t, filepath.Join(path, "inside")) != "kept" {
		t.Fatalf("left %v", found)
	}
}

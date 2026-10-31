package config

import (
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"testing"
	"unicode"
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
	// Python's strip() takes the unit separator, which no line break splits on, off both ends
	os.WriteFile(path, []byte("\x1fexport\x20\x1fKEY\x1f=\x1fv\x1f\n"), 0o600)
	if env, err := RepoEnv("/code/acme"); err != nil || !reflect.DeepEqual(env, map[string]string{"KEY": "v"}) {
		t.Fatalf("got %v %v", env, err)
	}
	os.WriteFile(path, []byte("A=1\nsecret value\n"), 0o600)
	if _, err := RepoEnv("/code/acme"); err == nil || !strings.HasSuffix(err.Error(), "acme.env:2: not a KEY=value line") {
		t.Fatalf("got %v", err)
	}
}

// Space is the set SpaceClass names, so a rune and a regular expression read whitespace alike.
func TestSpaceIsSpaceClass(t *testing.T) {
	class := regexp.MustCompile(SpaceClass)
	for r := rune(0); r <= unicode.MaxRune; r++ {
		if Space(r) != class.MatchString(string(r)) {
			t.Fatalf("%U: Space says %v, SpaceClass the opposite", r, Space(r))
		}
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

// A file whose name cannot name a harness, a backup say, is no manifest: not TOML, it refuses
// nothing, where one naming a harness is refused.
func TestOnlyAHarnesssNameIsAManifest(t *testing.T) {
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	for file, refused := range map[string]bool{"acme copy.toml": false, "acme.toml": true} {
		if err := os.WriteFile(filepath.Join(adapters, file), []byte("[effort\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := Manifests(); (err != nil) != refused {
			t.Errorf("%s: refused %v", file, err)
		}
		os.Remove(filepath.Join(adapters, file))
	}
}

// Int reads no more digits than PYTHONINTMAXSTRDIGITS lets Python's int() read: a sign and
// underscores aside, leading zeros among them, and 4300 where the variable is unset or refused.
func TestIntReadsAsManyDigitsAsPython(t *testing.T) {
	nines := func(n int) string { return strings.Repeat("9", n) }
	for _, c := range []struct {
		limit, text string
		read        bool
	}{
		{"", nines(4300), true}, {"", nines(4301), false}, {"639", nines(4301), false},
		{"640", "-" + nines(640), true}, {"640", nines(641), false}, {"640", "0" + nines(640), false},
		{"640", strings.Join(strings.Split(nines(640), ""), "_"), true},
		{" +0700", nines(700), true}, {"0", nines(5000), true}, {"-0", nines(5000), true},
	} {
		t.Setenv("PYTHONINTMAXSTRDIGITS", c.limit)
		if read := Int(c.text) != nil; read != c.read {
			t.Errorf("PYTHONINTMAXSTRDIGITS=%q, %d characters: read %v", c.limit, len(c.text), read)
		}
	}
}

// Int reads a digit of any script Python's int() reads, and only those: a script Unicode added
// after Python's release is no number, though Go's own unicode tables call it a digit.
func TestIntReadsPythonsDigits(t *testing.T) {
	for text, want := range map[string]string{"\u0663": "3", "-\U0001D7D7_\uFF11": "-91", "\U0001E4F9": "9",
		"\U0001CCF4": "", "\U00010D40": "", "\u00B2": "", "\u2167": ""} {
		if got := Int(text); got == nil && want != "" || got != nil && got.String() != want {
			t.Errorf("Int(%+q) = %v, want %q", text, got, want)
		}
	}
}

func TestManifestPathsReadTheHarnesssEnvironment(t *testing.T) {
	names := []string{"~/.acme", "$ACME_HOME", "~/.acme-$AGENTKIT_ACCOUNT", "${ACME_STATE:-~/.acme-state}", "$$ACME_HOME", "relative/dir", "${EMPTY:-fallback}/y", "$UNSET/z"}
	env := map[string]string{"HOME": "/home/acme", "ACME_HOME": "/opt/acme", "AGENTKIT_ACCOUNT": "", "EMPTY": ""}
	// as Python's config.manifest_paths reads them: an empty or unset variable with no default skips its path
	want := []string{"/home/acme/.acme", "/opt/acme", "/home/acme/.acme-state", "/code/widgets/$ACME_HOME", "/code/widgets/relative/dir", "/code/widgets/fallback/y"}
	if got := ManifestPaths(names, env, "/code/widgets"); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %q", got)
	}
}

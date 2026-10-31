package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func rememberIn(t *testing.T, text string) string {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	path := filepath.Join(home, ".agentkit", "config.toml")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// A seat's models go into [defaults], and the whole file is written as Python's save writes it:
// [tiers] gone but its pace_margin, a free provider no model names gone, a hosting harness's
// provider named by its label, every other key and table kept in place.
func TestRememberDefaultsWritesWhatPythonWrites(t *testing.T) {
	path := rememberIn(t, `# mine
within = 2.5
note = "ünï \"q\""
max_runs = 3

[tiers]
A = ["opus"]
B = ["opus", "mimo"]
pace_margin = 7

[models.opus]
provider = "anthropic"
effort = "xhigh"
model = "claude-opus-5-5"
harness = "claude"
extra = {deep = {k = 1}}

[models.mimo]
harness = "opencode"
model = "mimo/mimo-v2.6-pro"
effort = "high"
provider = "opencode"

[providers.anthropic]
mode = "subscription"
accounts = []

[providers.opencode]
maker = "Xiaomi"

[providers.loose]
mode = "free"

[machines."box one"]

[google_cloud]
active = false
zones = ["a", "b"]
[[google_cloud.pool]]
size = 2
[[google_cloud.pool]]
size = 4
[google_cloud.deep.deeper]
x = 1
`)
	if err := RememberDefaults("mimo", []string{"opus"}, []string{"mimo"}); err != nil {
		t.Fatal(err)
	}
	// as Python ak's config.remember_defaults wrote it from the same file
	want := `# agentkit's config, written by the menu's ` + "`c`" + ` screen. It is rewritten whole on every change,
# so a comment left here would not survive it; unknown keys are kept as they are.

max_runs = 3
pace_margin = 7
within = 2.5
note = "ünï \"q\""

[defaults]
orchestrator = "mimo"
workers = ["opus"]
reviewers = ["mimo"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"
extra = {deep = {k = 1}}

[models.mimo]
harness = "opencode"
model = "mimo/mimo-v2.6-pro"
effort = "high"
provider = "opencode"

[providers.anthropic]
mode = "subscription"
accounts = []

[providers.opencode]
maker = "Xiaomi"
name = "OpenCode"

[machines]

[machines."box one"]

[google_cloud]
active = false
zones = ["a", "b"]

[[google_cloud.pool]]
size = 2

[[google_cloud.pool]]
size = 4

[google_cloud.deep]

[google_cloud.deep.deeper]
x = 1
`
	if got, _ := os.ReadFile(path); string(got) != want {
		t.Fatalf("wrote:\n%s\nwant:\n%s", got, want)
	}
	if info, _ := os.Stat(path); info.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", info.Mode())
	}
}

// A file holding no table reads as the shipped config, its own keys over it.
func TestRememberDefaultsKeepsAModelessFilesKeys(t *testing.T) {
	path := rememberIn(t, "max_runs = 3\nextra = \"x\"\n")
	if err := RememberDefaults("opus", []string{"opus"}, nil); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(path)
	head := "unknown keys are kept as they are.\n\nmax_runs = 3\npace_margin = 10\nwithin = 5\nextra = \"x\"\n\n" +
		"[defaults]\norchestrator = \"opus\"\nworkers = [\"opus\"]\n\n[models.fable]\n"
	if !strings.Contains(string(got), head) || !strings.HasSuffix(string(got), "\n\n[google_cloud]\nactive = false\nmax_month = 0\n") {
		t.Fatalf("wrote:\n%s", got)
	}
}

// Defaults the file means already, its reviewers left to its workers, leave it as written.
func TestRememberDefaultsLeavesAFileMeaningThem(t *testing.T) {
	text := "# mine\n[defaults]\norchestrator = \"opus\"\nworkers = [\"opus\"]\nreviewers = [\"opus\"]\n" +
		"[models.opus]\nharness = \"claude\"\nmodel = \"m\"\neffort = \"high\"\nprovider = \"p\"\n[providers.p]\n"
	path := rememberIn(t, text)
	if err := RememberDefaults("opus", []string{"opus"}, nil); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(path); string(got) != text {
		t.Fatalf("rewrote it:\n%s", got)
	}
}

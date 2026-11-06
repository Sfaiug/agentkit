//go:build unix

package doctor

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const models = `[defaults]
orchestrator = "one"
workers = ["one"]

[models.one]
harness = "acme"
model = "acme-1"
effort = "high"
provider = "acme"

[models.two]
harness = "acme"
model = "acme-2"
effort = "low"
provider = "acme"

[providers.acme]
mode = "subscription"
accounts = ["first", "second"]
`

// home is a HOME holding that config.toml, whose adapter directory is the one returned.
func home(t *testing.T, config string) (string, string) {
	t.Helper()
	root, adapters := t.TempDir(), t.TempDir()
	for key, value := range map[string]string{"HOME": root, "USERPROFILE": root, "AGENTKIT_ADAPTER_DIR": adapters,
		"AGENTKIT_TMUX_SOCKET": "doctor-test", "XDG_RUNTIME_DIR": t.TempDir()} {
		t.Setenv(key, value)
	}
	if err := os.MkdirAll(filepath.Join(root, ".agentkit", "secrets"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".agentkit", "config.toml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	return root, adapters
}

// Each read Go cannot make says nothing and leaves all of it to Python.
func TestAReadGoCannotMakeSaysNothing(t *testing.T) {
	for name, arrange := range map[string]func(t *testing.T, root string){
		"ak may rent": func(t *testing.T, root string) {
			config := filepath.Join(root, ".agentkit", "config.toml")
			os.WriteFile(config, []byte(models+"\n[google_cloud]\nactive = true\n"), 0o600)
		},
		"no adapter to ask": func(t *testing.T, _ string) { t.Setenv("AGENTKIT_ADAPTER_DIR", "") },
	} {
		t.Run(name, func(t *testing.T) {
			root, _ := home(t, models)
			arrange(t, root)
			var out, errOut bytes.Buffer
			if _, read := Report(&out, &errOut); read || out.Len() != 0 || errOut.Len() != 0 {
				t.Fatalf("read=%v stdout=%q stderr=%q", read, out.String(), errOut.String())
			}
		})
	}
}

// A config refused comes after what doctor reads without one, though a key is there too.
func TestARefusedConfigFollowsTheHostLines(t *testing.T) {
	root, _ := home(t, "[defaults]\norchestrator = \"one\"\n")
	os.WriteFile(filepath.Join(root, ".agentkit", "secrets", "google-cloud.json"), []byte("{}"), 0o600)
	var out, errOut bytes.Buffer
	code, read := Report(&out, &errOut)
	if code != 2 || !read || strings.Count(out.String(), "\n") != 2 || !strings.HasPrefix(errOut.String(), "ak doctor: ") {
		t.Fatalf("code=%d read=%v stdout=%q stderr=%q", code, read, out.String(), errOut.String())
	}
}

// Each subscription's login is asked, told its name and provider, and the first to list a model
// says what it takes.
func TestTheFirstLoginToListAModelSaysItsEfforts(t *testing.T) {
	_, adapters := home(t, models)
	script := `#!/bin/sh
[ "$AGENTKIT_PROVIDER" = acme ] || exit 1
case "$AGENTKIT_ACCOUNT" in
first) printf 'acme-1\tAcme 1\tlow\n' ;;
second) printf 'acme-1\tAcme 1\thigh\nacme-2\tAcme 2\tmedium high\n' ;;
esac
`
	if err := os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if code, read := Report(&out, &errOut); code != 1 || !read {
		t.Fatalf("code=%d read=%v stderr=%q", code, read, errOut.String())
	}
	for _, line := range []string{"effort  one: acme-1 takes low, not high", "effort  two: acme-2 takes medium high, not low"} {
		if !strings.Contains(out.String(), line+"\n") {
			t.Errorf("no %q in %q", line, out.String())
		}
	}
}

// A helper still holding the adapter's output after it exits does not cost the listing.
func TestAListingOutlivedByAHelperStands(t *testing.T) {
	_, adapters := home(t, models)
	script := "#!/bin/sh\nsleep 2 &\nprintf 'acme-1\\tAcme 1\\tlow\\n'\n"
	if err := os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	Report(&out, &errOut)
	if !strings.Contains(out.String(), "effort  one: acme-1 takes low, not high\n") {
		t.Fatalf("stdout=%q stderr=%q", out.String(), errOut.String())
	}
}

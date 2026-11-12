package update

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

const testConfig = "[models.acme]\nharness='gamma'\nmodel='acme-1'\neffort='low'\nprovider='acme'\n[providers.acme]\nmode='subscription'\n"
const testManifest = "[update]\nversion = ['acme-cli', '--version']\nupgrade = ['acme-cli', 'upgrade']\n"

// sandbox is a HOME whose one harness runs acme-cli, none on PATH, and the checkout ak runs from.
func sandbox(t *testing.T) (home, repo string) {
	t.Helper()
	home, repo = t.TempDir(), t.TempDir()
	adapters := t.TempDir()
	for path, content := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): testConfig,
		filepath.Join(adapters, "gamma.toml"):           testManifest,
		filepath.Join(repo, "tests", "live.sh"):         "exit 0\n",
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_ADAPTER_DIR": adapters} {
		t.Setenv(key, value)
	}
	return home, repo
}

func TestAProgramARelativePathEntryFindsIsInstalled(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the program is a shell script")
	}
	back, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(back) })
	search := os.Getenv("PATH")
	for _, entry := range []string{"tools", ".", ""} {
		// one whose version command fails is installed and broken, never absent
		for shown, program := range map[string]string{"2.1.0": "echo 2.1.0", "not installed": "exit 1"} {
			home, repo := sandbox(t)
			tools := filepath.Join(home, "tools")
			if err := os.Mkdir(tools, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(tools, "acme-cli"), []byte("#!/bin/sh\n"+program+"\n"), 0o700); err != nil {
				t.Fatal(err)
			}
			place := tools
			if entry == "tools" {
				place = home
			}
			if err := os.Chdir(place); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", entry+string(os.PathListSeparator)+search)
			var out, errOut bytes.Buffer
			// no `skipped: not installed here` comes first
			code, err := Main(repo, true, &out, &errOut)
			want := "gamma " + shown + " (cannot be reverted: it offers no versioned reinstall): acme-cli upgrade\n"
			if code != 0 || err != nil || !strings.HasPrefix(out.String(), want) {
				t.Errorf("PATH entry %q, %s: the dry run gave %d, %v, %q", entry, program, code, err, out.String())
			}
		}
	}
}

func TestADowngradeIsReadAsPythonReadsOne(t *testing.T) {
	for _, each := range []struct {
		old, new string
		down     bool
	}{
		{"2.2.0 (Acme Code)", "2.1.9 (Acme Code)", true},
		{"2.1.0 (Acme Code)", "2.10.0 (Acme Code)", false},
		{"Acme Code 1.4.1; build 1.4.1-R4600.1", "Acme Code 1.4.1; build 1.4.1-R4503.1", true},
		{"Acme Code 1.4.1; build 1.4.1-R4503.1", "Acme Code 1.4.1", false}, // a label alone names no build
		{"Acme Code 1.4.2", "Acme Code 1.4.1; build 1.4.1-R4600.1", true},
		{"٢.١.٠", "2.0.9", true}, // Python's int() reads any script's digits
		{"", "1.0.0", false},
	} {
		if down := downgrade(each.old, each.new); down != each.down {
			t.Errorf("%q -> %q: downgrade %t", each.old, each.new, down)
		}
	}
}

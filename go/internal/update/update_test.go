package update

import (
	"bytes"
	"errors"
	"os"
	"os/exec"
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

// wrote is whether ak has made its own folders under home.
func wrote(home string) bool {
	_, err := os.Stat(filepath.Join(home, ".agentkit", "runs"))
	return err == nil
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
			if _, err := run(repo, false, &out, &errOut); !errors.Is(err, ErrPython) || wrote(home) {
				t.Errorf("PATH entry %q, %s: the update left err=%v wrote=%t stdout=%q", entry, program, err, wrote(home), out.String())
			}
			code, err := run(repo, true, &out, &errOut)
			want := "gamma " + shown + " (cannot be reverted: it offers no versioned reinstall): acme-cli upgrade\n"
			if code != 0 || err != nil || !strings.HasPrefix(out.String(), want) {
				t.Errorf("PATH entry %q, %s: the dry run gave %d, %v, %q", entry, program, code, err, out.String())
			}
		}
	}
}

func TestALogNotInUTF8IsLeftToPythonBeforeAnythingIsWritten(t *testing.T) {
	home, repo := sandbox(t)
	checkout := filepath.Join(home, "agentkit")
	if err := os.Mkdir(checkout, 0o700); err != nil {
		t.Fatal(err)
	}
	git := func(args ...string) {
		t.Helper()
		if said, err := exec.Command("git", append([]string{"-C", checkout}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %q: %v: %s", args, err, said)
		}
	}
	git("init", "-q")
	git("-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-q", "--allow-empty", "-m", "first")
	git("config", "i18n.logOutputEncoding", "ISO-8859-1")
	var out, errOut bytes.Buffer
	if _, err := run(repo, true, &out, &errOut); !errors.Is(err, ErrPython) || wrote(home) || out.Len() > 0 {
		t.Errorf("err=%v wrote=%t stdout=%q", err, wrote(home), out.String())
	}
	git("config", "--unset", "i18n.logOutputEncoding")
	if code, err := run(repo, true, &out, &errOut); code != 0 || err != nil || !strings.Contains(out.String(), " · ") {
		t.Errorf("a log in UTF-8 gave %d, %v, %q", code, err, out.String())
	}
}

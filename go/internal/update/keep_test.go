package update

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// harnessHome is sandbox's HOME with acme-cli on PATH: on 1.0.0, upgrading to 2.0.0, and the
// channel's latest 2.0.0, each call of it kept in HOME/calls.
func harnessHome(t *testing.T) (home, repo string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the harness is a shell script")
	}
	home, repo = sandbox(t)
	tools := filepath.Join(home, "tools")
	for path, content := range map[string]string{
		filepath.Join(os.Getenv("AGENTKIT_ADAPTER_DIR"), "gamma.toml"): testManifest + "latest = ['acme-cli', 'latest']\n",
		filepath.Join(home, "installed"):                               "1.0.0\n",
		filepath.Join(tools, "acme-cli"): "#!/bin/sh\necho \"$1\" >>\"$HOME/calls\"\ncase $1 in\n" +
			"--version) cat \"$HOME/installed\" ;;\nupgrade) echo 2.0.0 >\"$HOME/installed\" ;;\nlatest) echo 2.0.0 ;;\nesac\n",
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", tools+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("AK_OWNER", "") // Background marks this process; the test's own mark comes back
	if err := config.EnsureDirs(); err != nil {
		t.Fatal(err)
	}
	return home, repo
}

func calls(t *testing.T, home string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(home, "calls"))
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		t.Fatal(err)
	}
	return strings.Fields(string(data))
}

func TestABackgroundUpgradeWhoseGateIsGoneInstallsNothingAndSaysWhy(t *testing.T) {
	home, repo := harnessHome(t)
	if err := os.Remove(filepath.Join(repo, "tests", "live.sh")); err != nil {
		t.Fatal(err)
	}
	code := Background(repo, "gamma")
	said, _ := os.ReadFile(saidPath())
	want := `{"harness": "gamma", "code": 1, "lines": ["update: Error('no acceptance gate at ` +
		filepath.Join(repo, "tests", "live.sh") + `; an unverified upgrade is not one')"]}`
	if got := calls(t, home); code != 1 || strings.Join(got, " ") != "--version" || string(said) != want {
		t.Fatalf("exit %d, calls %q, said %s", code, got, said)
	}
}

func TestATickHandsOverAHarnessItCouldNotMoveBeforeAskingItsRelease(t *testing.T) {
	home, _ := harnessHome(t)
	checkout := filepath.Join(home, "agentkit") // ~/agentkit's own tick
	if err := os.Mkdir(checkout, 0o700); err != nil {
		t.Fatal(err)
	}
	// its installer is writing it: no snapshot Go can take
	for path, content := range map[string]string{
		filepath.Join(os.Getenv("AGENTKIT_ADAPTER_DIR"), "gamma.toml"): testManifest +
			"latest = ['acme-cli', 'latest']\n[snapshot]\nfiles = ['acme-cli']\nlock = 'installing'\n",
		filepath.Join(home, "tools", "installing"): "",
	} {
		if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	err := KeepCurrent(config.Resolve(checkout), func(line string) { t.Errorf("said %q", line) }, nil)
	_, recorded := os.Stat(filepath.Join(home, ".agentkit", "state", "harness-latest.json"))
	if got := calls(t, home); !errors.Is(err, ErrPython) || strings.Join(got, " ") != "--version" || recorded == nil {
		t.Fatalf("gave %v, calls %q, recorded %v", err, got, recorded == nil)
	}
}

//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"maps"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// signedOut is a home holding a project whose night failed one test, its config.toml ending in
// more, marked to run on one model whose claude is signed out, and the night reads row read there
// under env: so whatever this host is signed in to, Go carries the fix's launch up to its pick,
// which refuses the run, starting no driver.  What the row logged, and its error.
func signedOut(t *testing.T, more string, env map[string]string) (ak, said string, err error) {
	t.Helper()
	ak, _ = checkoutHome(t, "---\ntests: true\nnightly: printf '%s' "+
		`'{"started":"night-1","passed":false,"failed":["tests/a.py::b"]}'`+"\n---\n# acme\n")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[defaults]\norchestrator = 'opus'\nworkers = ['opus']\nreviewers = ['opus']\n"+
		"[models.opus]\nharness = 'claude'\nmodel = 'opus'\neffort = 'high'\nprovider = 'acme'\n[providers.acme]\nmode = 'subscription'\n"+more)
	tool := filepath.Join(t.TempDir(), "claude")
	put(t, tool, "#!/bin/sh\nexit 1\n")
	if err := os.Chmod(tool, 0o700); err != nil {
		t.Fatal(err)
	}
	maps.Copy(env, map[string]string{"AK_MAX_RUNS": "0", "AGENTKIT_RUN_DIR": "", "CLAUDE_CONFIG_DIR": "", "CLAUDE_CODE_OAUTH_TOKEN": "",
		"PATH": filepath.Dir(tool) + string(os.PathListSeparator) + os.Getenv("PATH")})
	for key, value := range env {
		t.Setenv(key, value)
	}
	var out bytes.Buffer
	err = (&ticking{clock: time.Now, log: newLog(&out, io.Discard)}).nights()
	if err != nil && !errors.Is(err, errLeft) {
		t.Fatalf("night read: %v; %s", err, out.String())
	}
	return ak, out.String(), err
}

// A night whose fix Go leaves to Python (its provider lists several logins, among which Python's
// turn picks) hands the tick over with nothing written: no task, no file of names, no stamp.
func TestANightLeftToPythonWritesNothing(t *testing.T) {
	ak, _, err := signedOut(t, "accounts = ['shoal', 'reef']\n", map[string]string{"AK_RUN_DEPTH": "0", "AK_PARENT_RUN": ""})
	if !errors.Is(err, errLeft) {
		t.Fatalf("carried it: %v", err)
	}
	if written, _ := filepath.Glob(filepath.Join(ak, "tasks", "*", "night-*")); len(written) > 0 {
		t.Errorf("wrote %v", written)
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "nightly.json")); err == nil {
		t.Error("stamped the night")
	}
}

// A night's fix descends from nothing that made it, whatever run the tick is under: its receipt
// is at depth 0 with no parent, as Python's records a seat launch, refused at its pick or not.
func TestANightFixDescendsFromNothing(t *testing.T) {
	_, said, _ := signedOut(t, "", map[string]string{"AK_RUN_DEPTH": "2", "AK_PARENT_RUN": "parent-run"})
	found := 0
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); record != nil && record.Truthy("night") {
			found++
			if record.Truthy("run_depth") || record.Get("parent_run") != nil {
				t.Errorf("its receipt took the tick's ancestry: %s", run.Line(record))
			}
		}
	}
	if found != 1 {
		t.Fatalf("%d night runs, logging %q", found, said)
	}
}
